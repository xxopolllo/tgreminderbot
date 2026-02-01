import os


BOT_TOKEN = os.getenv("REMINDER_BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "data/reminders.db")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
DATE_FORMAT = os.getenv("DATE_FORMAT", "%d.%m.%Y %H:%M")
