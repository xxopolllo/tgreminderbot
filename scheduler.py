from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo

import storage
from models import Reminder


PERIODS = {
    "one_time": None,
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "biweekly": timedelta(weeks=2),
    "monthly": relativedelta(months=1),
    "quarterly": relativedelta(months=3),
}


def compute_next_run(base_time: datetime, period: str, *, now: datetime) -> datetime:
    delta = PERIODS.get(period)
    if delta is None:
        raise ValueError(f"Unknown period: {period}")

    next_time = base_time
    while next_time <= now:
        if isinstance(delta, relativedelta):
            next_time = next_time + delta
        else:
            next_time = next_time + delta
    return next_time


def normalize_next_run(start_time: datetime, period: str, *, now: datetime) -> datetime:
    if period == "one_time":
        return start_time if start_time > now else now
    if start_time > now:
        return start_time
    return compute_next_run(start_time, period, now=now)


def build_scheduler(timezone: str) -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone=ZoneInfo(timezone))


def _job_id(reminder_id: int) -> str:
    return f"reminder_{reminder_id}"


def unschedule_reminder(scheduler: AsyncIOScheduler, reminder_id: int) -> None:
    job_id = _job_id(reminder_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def schedule_reminder(
    scheduler: AsyncIOScheduler,
    reminder: Reminder,
    bot,
    db_path: str,
    timezone: str,
) -> None:
    job_id = _job_id(reminder.id)
    run_date = reminder.next_run
    scheduler.add_job(
        send_reminder,
        "date",
        id=job_id,
        run_date=run_date,
        args=[reminder.id, bot, db_path, timezone, scheduler],
        replace_existing=True,
    )


async def send_reminder(
    reminder_id: int,
    bot,
    db_path: str,
    timezone: str,
    scheduler: AsyncIOScheduler,
) -> None:
    reminder = storage.get_reminder(db_path, reminder_id)
    if not reminder or reminder.status != "active":
        return

    try:
        await bot.send_message(reminder.chat_ref, reminder.text)
        now = datetime.now(ZoneInfo(timezone))
        storage.update_reminder(db_path, reminder_id, last_sent_at=now)
    except Exception:
        now = datetime.now(ZoneInfo(timezone))
    if reminder.period == "one_time":
        storage.deactivate_reminder(db_path, reminder_id)
        return
    next_run = compute_next_run(reminder.next_run, reminder.period, now=now)
    storage.update_reminder(db_path, reminder_id, next_run=next_run)
    refreshed = storage.get_reminder(db_path, reminder_id)
    if refreshed:
        schedule_reminder(scheduler, refreshed, bot, db_path, timezone)
