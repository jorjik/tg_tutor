from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.middleware.subscription import ActiveSubscription, SubscriptionMiddleware
from app.db.session import AsyncSessionLocal
from app.services.chat_service import answer_user_message, get_or_create_user, reset_user_conversation

logger = logging.getLogger(__name__)

router = Router(name="chat")
router.message.middleware(SubscriptionMiddleware())


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    if not message.from_user:
        await message.answer("Не удалось определить пользователя.")
        return

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            locale=message.from_user.language_code,
        )
        await reset_user_conversation(session, user)
        await session.commit()

    await message.answer("Память очищена. Начинаем новый диалог.")


@router.message(F.text)
async def on_user_text(
    message: Message,
    active_sub: ActiveSubscription | None = None,
) -> None:
    if not message.from_user or not message.text:
        await message.answer("Я могу отвечать только на текстовые сообщения.")
        return

    if message.text.startswith("/"):
        return

    # Модель берётся из тарифа пользователя; если middleware не отработал — из конфига
    openai_model = active_sub.plan.openai_model if active_sub else None

    try:
        async with AsyncSessionLocal() as session:
            result = await answer_user_message(
                session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                locale=message.from_user.language_code,
                user_text=message.text,
                openai_model=openai_model,
            )
    except Exception:
        logger.exception("Ошибка при обработке сообщения пользователя")
        await message.answer("Сервис временно недоступен. Попробуйте ещё раз чуть позже.")
        return

    await message.answer(result.answer)
