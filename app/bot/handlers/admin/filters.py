from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import get_settings


class AdminFilter(BaseFilter):
    """Passes only if the update comes from a configured admin Telegram user."""

    async def __call__(self, update: Message | CallbackQuery) -> bool:
        uid = update.from_user.id if update.from_user else 0
        return uid in get_settings().get_admin_ids()
