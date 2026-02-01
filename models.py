from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Reminder:
    id: int
    owner_user_id: int
    text: str
    next_run: datetime
    period: str
    chat_ref: str
    status: str
    created_at: datetime
    updated_at: datetime
    last_sent_at: Optional[datetime]
