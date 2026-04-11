from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

from app.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.chat_service import get_or_create_user
from app.services.subscription_service import (
    ActiveSubscription,
    _MISS,
    _cache_get_sub,
    _cache_set_sub,
    check_limits,
    get_active_subscription,
)


class SubscriptionMiddleware(BaseMiddleware):
    """Проверяет активную подписку и лимиты запросов перед текстовыми сообщениями.

    При успехе добавляет в data["active_sub"] объект ActiveSubscription,
    чтобы обработчик мог использовать модель из тарифа.
    Команды (начинаются с /) пропускаются без проверки.
    """

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        # Пропускаем всё, что не является обычным текстом или является командой
        if not isinstance(event, Message):
            return await handler(event, data)
        if not event.text or event.text.startswith("/"):
            return await handler(event, data)
        if not event.from_user:
            return await handler(event, data)
        if event.from_user.id in get_settings().get_admin_ids():
            return await handler(event, data)

        async with AsyncSessionLocal() as session:
            user = await get_or_create_user(
                session,
                telegram_id=event.from_user.id,
                username=event.from_user.username,
                locale=event.from_user.language_code,
            )
            await session.commit()

            cached = _cache_get_sub(user.id)
            if cached is _MISS:
                active_sub = await get_active_subscription(session, user.id)
                _cache_set_sub(user.id, active_sub)
            else:
                active_sub = cached  # type: ignore[assignment]

            if active_sub is None:
                await event.answer(
                    "У вас нет активной подписки.\n\n"
                    "Используйте /subscribe, чтобы выбрать тариф и оформить подписку."
                )
                return

            allowed, reason = await check_limits(session, user.id, active_sub)
            if not allowed:
                await event.answer(f"⛔ {reason}")
                return

        data["active_sub"] = active_sub
        return await handler(event, data)


__all__ = ["SubscriptionMiddleware", "ActiveSubscription"]
