import asyncio
from datetime import datetime
import re
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from zoneinfo import ZoneInfo

import config
import scheduler as reminder_scheduler
import storage


class AddReminder(StatesGroup):
    text = State()
    date = State()
    period = State()
    chat = State()


class EditReminder(StatesGroup):
    choose_id = State()
    choose_field = State()
    enter_value = State()
    confirm = State()


PERIOD_LABELS = {
    "daily": "Ежедневно",
    "weekly": "Еженедельно",
    "biweekly": "Раз в две недели",
    "quarterly": "Раз в квартал",
}

LABEL_TO_PERIOD = {v: k for k, v in PERIOD_LABELS.items()}


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Добавить напоминание")],
            [KeyboardButton(text="Список напоминаний")],
        ],
        resize_keyboard=True,
    )


def period_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=PERIOD_LABELS["daily"])],
            [KeyboardButton(text=PERIOD_LABELS["weekly"])],
            [KeyboardButton(text=PERIOD_LABELS["biweekly"])],
            [KeyboardButton(text=PERIOD_LABELS["quarterly"])],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def edit_field_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Текст")],
            [KeyboardButton(text="Дата")],
            [KeyboardButton(text="Периодичность")],
            [KeyboardButton(text="Группа")],
            [KeyboardButton(text="Удалить")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def save_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Сохранить"),
                KeyboardButton(text="Удалить"),
                KeyboardButton(text="Отмена"),
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def edit_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Редактировать", callback_data="edit_reminders")]
        ]
    )


def parse_datetime(text: str, tz: ZoneInfo) -> Optional[datetime]:
    try:
        parsed = datetime.strptime(text.strip(), config.DATE_FORMAT)
        return parsed.replace(tzinfo=tz)
    except ValueError:
        return None


def normalize_chat_ref(text: str) -> Optional[str]:
    value = text.strip()
    if value.startswith("@"):
        return value
    if value.startswith("https://t.me/") or value.startswith("http://t.me/"):
        value = value.split("t.me/")[-1]
    elif value.startswith("t.me/"):
        value = value.split("t.me/")[-1]
    if value.startswith("+") or value.startswith("c/"):
        return None
    if re.fullmatch(r"-?\d+", value):
        return value
    if re.fullmatch(r"[A-Za-z0-9_]{4,}", value):
        return f"@{value}"
    return None


def extract_chat_ref(message: Message) -> Optional[str]:
    if message.forward_from_chat:
        chat = message.forward_from_chat
        if chat.username:
            return f"@{chat.username}"
        return str(chat.id)
    if message.text:
        return normalize_chat_ref(message.text)
    return None


async def start_handler(message: Message) -> None:
    if message.chat.type != ChatType.PRIVATE:
        return
    await message.answer(
        "Привет! Я помогу настроить напоминания для групп.",
        reply_markup=main_keyboard(),
    )


async def id_handler(message: Message) -> None:
    chat = message.chat
    title = chat.title or chat.full_name or "Без названия"
    await message.answer(f"ID чата: {chat.id}\nНазвание: {title}")


async def add_start(message: Message, state: FSMContext) -> None:
    if message.chat.type != ChatType.PRIVATE:
        return
    await state.clear()
    await state.set_state(AddReminder.text)
    await message.answer("Введите текст напоминания.")


async def add_text(message: Message, state: FSMContext) -> None:
    await state.update_data(text=message.text.strip())
    await state.set_state(AddReminder.date)
    await message.answer("Введите дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ (MSK).")


async def add_date(message: Message, state: FSMContext) -> None:
    tz = ZoneInfo(config.TIMEZONE)
    parsed = parse_datetime(message.text or "", tz)
    if not parsed:
        await message.answer("Неверный формат. Попробуйте еще раз.")
        return
    await state.update_data(date=parsed)
    await state.set_state(AddReminder.period)
    await message.answer("Выберите периодичность.", reply_markup=period_keyboard())


async def add_period(message: Message, state: FSMContext) -> None:
    period = LABEL_TO_PERIOD.get(message.text or "")
    if not period:
        await message.answer("Выберите период из списка.")
        return
    await state.update_data(period=period)
    await state.set_state(AddReminder.chat)
    await message.answer(
        "Укажите @username/ссылку/ID. Для закрытых групп добавьте бота в группу и отправьте там /id."
    )


async def add_chat(
    message: Message,
    state: FSMContext,
    bot: Bot,
    scheduler,
) -> None:
    chat_ref = extract_chat_ref(message)
    if not chat_ref:
        await message.answer(
            "Не смог определить группу. Перешлите сообщение из группы или укажите @username/ссылку/ID."
        )
        return
    data = await state.get_data()
    tz = ZoneInfo(config.TIMEZONE)
    next_run = reminder_scheduler.normalize_next_run(
        data["date"], data["period"], now=datetime.now(tz)
    )
    reminder_id = storage.add_reminder(
        config.DB_PATH, data["text"], next_run, data["period"], chat_ref
    )
    reminder = storage.get_reminder(config.DB_PATH, reminder_id)
    if reminder:
        reminder_scheduler.schedule_reminder(
            scheduler, reminder, bot, config.DB_PATH, config.TIMEZONE
        )
    await state.clear()
    await message.answer(
        "Напоминание создано.",
        reply_markup=main_keyboard(),
    )


async def list_reminders(message: Message, state: FSMContext) -> None:
    if message.chat.type != ChatType.PRIVATE:
        return
    await state.clear()
    reminders = list(storage.list_active_reminders(config.DB_PATH))
    if not reminders:
        await message.answer("Активных напоминаний нет.", reply_markup=main_keyboard())
        return
    lines = []
    ids = []
    tz = ZoneInfo(config.TIMEZONE)
    for idx, reminder in enumerate(reminders, start=1):
        next_run = reminder.next_run.astimezone(tz).strftime(config.DATE_FORMAT)
        lines.append(
            f"{idx}) {reminder.text} | {next_run} | {PERIOD_LABELS.get(reminder.period)} | {reminder.chat_ref}"
        )
        ids.append(reminder.id)
    await state.update_data(list_ids=ids)
    await message.answer(
        "Список активных напоминаний:\n" + "\n".join(lines),
        reply_markup=main_keyboard(),
    )
    await message.answer("Хотите редактировать?", reply_markup=edit_inline_keyboard())


async def edit_start(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    data = await state.get_data()
    if not data.get("list_ids"):
        await call.message.answer("Сначала запросите список напоминаний.")
        return
    await state.set_state(EditReminder.choose_id)
    await call.message.answer("Введите номер напоминания из списка.")


async def edit_choose_id(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    ids = data.get("list_ids") or []
    try:
        idx = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("Введите номер из списка.")
        return
    if idx < 1 or idx > len(ids):
        await message.answer("Такого номера нет. Попробуйте снова.")
        return
    reminder_id = ids[idx - 1]
    await state.update_data(reminder_id=reminder_id)
    await state.set_state(EditReminder.choose_field)
    await message.answer("Что изменить?", reply_markup=edit_field_keyboard())


async def edit_choose_field(message: Message, state: FSMContext) -> None:
    field_map = {
        "Текст": "text",
        "Дата": "date",
        "Периодичность": "period",
        "Группа": "chat",
        "Удалить": "delete",
    }
    field = field_map.get(message.text or "")
    if not field:
        await message.answer("Выберите поле из списка.")
        return
    await state.update_data(edit_field=field)
    if field == "delete":
        await state.set_state(EditReminder.confirm)
        await message.answer("Подтвердите удаление.", reply_markup=save_keyboard())
        return
    await state.set_state(EditReminder.enter_value)
    if field == "period":
        await message.answer("Выберите период.", reply_markup=period_keyboard())
    elif field == "date":
        await message.answer("Введите дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ (MSK).")
    elif field == "chat":
        await message.answer(
            "Укажите @username/ID. Для закрытых групп добавьте бота в группу и отправьте там /id."
        )
    else:
        await message.answer("Введите новый текст напоминания.")


async def edit_enter_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = data.get("edit_field")
    tz = ZoneInfo(config.TIMEZONE)
    if field == "period":
        period = LABEL_TO_PERIOD.get(message.text or "")
        if not period:
            await message.answer("Выберите период из списка.")
            return
        await state.update_data(new_value=period)
    elif field == "date":
        parsed = parse_datetime(message.text or "", tz)
        if not parsed:
            await message.answer("Неверный формат. Попробуйте еще раз.")
            return
        await state.update_data(new_value=parsed)
    elif field == "chat":
        chat_ref = extract_chat_ref(message)
        if not chat_ref:
            await message.answer(
                "Не смог определить группу. Перешлите сообщение из группы или укажите @username/ID."
            )
            return
        await state.update_data(new_value=chat_ref)
    else:
        await state.update_data(new_value=(message.text or "").strip())

    await state.set_state(EditReminder.confirm)
    await message.answer("Сохранить изменения?", reply_markup=save_keyboard())


async def edit_confirm(
    message: Message,
    state: FSMContext,
    bot: Bot,
    scheduler,
) -> None:
    if (message.text or "").strip() == "Отмена":
        await state.clear()
        await message.answer("Изменения отменены.", reply_markup=main_keyboard())
        return
    data = await state.get_data()
    if (message.text or "").strip() == "Удалить":
        data = await state.get_data()
        reminder_id = data.get("reminder_id")
        if reminder_id:
            storage.deactivate_reminder(config.DB_PATH, reminder_id)
            reminder_scheduler.unschedule_reminder(scheduler, reminder_id)
        await state.clear()
        await message.answer("Напоминание удалено.", reply_markup=main_keyboard())
        return
    if data.get("edit_field") == "delete":
        await message.answer("Нажмите «Удалить» или «Отмена».")
        return
    if (message.text or "").strip() != "Сохранить":
        await message.answer("Нажмите «Сохранить» или «Отмена».")
        return
    data = await state.get_data()
    reminder_id = data["reminder_id"]
    reminder = storage.get_reminder(config.DB_PATH, reminder_id)
    if not reminder:
        await state.clear()
        await message.answer("Напоминание не найдено.", reply_markup=main_keyboard())
        return

    field = data["edit_field"]
    new_value = data["new_value"]
    tz = ZoneInfo(config.TIMEZONE)

    update_kwargs = {}
    if field == "text":
        update_kwargs["text"] = new_value
    elif field == "chat":
        update_kwargs["chat_ref"] = new_value
    elif field == "date":
        next_run = reminder_scheduler.normalize_next_run(
            new_value, reminder.period, now=datetime.now(tz)
        )
        update_kwargs["next_run"] = next_run
    elif field == "period":
        base_time = reminder.next_run
        next_run = reminder_scheduler.normalize_next_run(
            base_time, new_value, now=datetime.now(tz)
        )
        update_kwargs["period"] = new_value
        update_kwargs["next_run"] = next_run

    storage.update_reminder(config.DB_PATH, reminder_id, **update_kwargs)
    reminder_scheduler.unschedule_reminder(scheduler, reminder_id)
    refreshed = storage.get_reminder(config.DB_PATH, reminder_id)
    if refreshed:
        reminder_scheduler.schedule_reminder(
            scheduler, refreshed, bot, config.DB_PATH, config.TIMEZONE
        )

    await state.clear()
    await message.answer("Изменения сохранены.", reply_markup=main_keyboard())


def setup_routes(router: Router) -> None:
    router.message.register(start_handler, F.text == "/start")
    router.message.register(id_handler, F.text == "/id")
    router.message.register(add_start, F.text == "Добавить напоминание")
    router.message.register(list_reminders, F.text == "Список напоминаний")
    router.callback_query.register(edit_start, F.data == "edit_reminders")

    router.message.register(add_text, AddReminder.text)
    router.message.register(add_date, AddReminder.date)
    router.message.register(add_period, AddReminder.period)
    router.message.register(add_chat, AddReminder.chat)

    router.message.register(edit_choose_id, EditReminder.choose_id)
    router.message.register(edit_choose_field, EditReminder.choose_field)
    router.message.register(edit_enter_value, EditReminder.enter_value)
    router.message.register(edit_confirm, EditReminder.confirm)


async def main() -> None:
    if not config.BOT_TOKEN:
        raise RuntimeError("REMINDER_BOT_TOKEN is required")

    storage.init_db(config.DB_PATH)
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    router = Router()
    setup_routes(router)
    dp.include_router(router)

    scheduler = reminder_scheduler.build_scheduler(config.TIMEZONE)
    scheduler.start()
    dp["scheduler"] = scheduler
    for reminder in storage.list_active_reminders(config.DB_PATH):
        reminder_scheduler.schedule_reminder(
            scheduler, reminder, bot, config.DB_PATH, config.TIMEZONE
        )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
