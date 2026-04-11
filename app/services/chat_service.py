from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Final

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import ChatMessage, User
from app.services.openai_client import get_openai_client
from app.services.subscription_service import increment_usage


@dataclass(slots=True)
class ChatTurnResult:
    answer: str


# ── Message history TTL cache ─────────────────────────────────────────────────

@dataclass(slots=True)
class _Msg:
    role: str
    content: str


_MSG_TTL: Final[float] = 600.0  # 10 minutes
_msg_cache: dict[int, tuple[list[_Msg], float]] = {}
_MSG_MISS = object()


def _cache_get_msgs(user_id: int) -> object:
    entry = _msg_cache.get(user_id)
    if entry is None:
        return _MSG_MISS
    msgs, ts = entry
    if time.monotonic() - ts > _MSG_TTL:
        _msg_cache.pop(user_id, None)
        return _MSG_MISS
    return msgs


def _cache_set_msgs(user_id: int, msgs: list[_Msg]) -> None:
    _msg_cache[user_id] = (msgs, time.monotonic())


def _invalidate_msg_cache(user_id: int) -> None:
    _msg_cache.pop(user_id, None)


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    locale: str | None,
) -> User:
    stmt = select(User).where(User.telegram_id == telegram_id).limit(1)
    user = await session.scalar(stmt)
    if user is not None:
        if username is not None:
            user.username = username
        if locale is not None:
            user.locale = locale
        return user

    user = User(
        telegram_id=telegram_id,
        username=username,
        locale=locale,
        conversation_summary=None,
    )
    session.add(user)
    await session.flush()
    return user


async def reset_user_conversation(session: AsyncSession, user: User) -> None:
    await session.execute(delete(ChatMessage).where(ChatMessage.user_id == user.id))
    user.conversation_summary = None
    _invalidate_msg_cache(user.id)


async def _load_recent_messages(session: AsyncSession, user_id: int, limit_pairs: int) -> list[_Msg]:
    cached = _cache_get_msgs(user_id)
    if cached is not _MSG_MISS:
        return cached  # type: ignore[return-value]
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit_pairs * 2)
    )
    rows = (await session.scalars(stmt)).all()
    rows.reverse()
    msgs = [_Msg(role=m.role, content=m.content) for m in rows]
    _cache_set_msgs(user_id, msgs)
    return msgs


def _build_openai_messages(summary: str | None, history: list[_Msg], user_text: str) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    if summary:
        payload.append(
            {
                "role": "system",
                "content": (
                    "Краткое резюме более старого диалога пользователя и ассистента:\n"
                    f"{summary}"
                ),
            }
        )

    for m in history:
        payload.append({"role": m.role, "content": m.content})

    payload.append({"role": "user", "content": user_text})
    return payload


async def answer_user_message(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
    locale: str | None,
    user_text: str,
    openai_model: str | None = None,
) -> ChatTurnResult:
    settings = get_settings()
    model = openai_model or settings.openai_model

    user = await get_or_create_user(session, telegram_id=telegram_id, username=username, locale=locale)
    history = await _load_recent_messages(session, user.id, settings.recent_user_messages)
    messages = _build_openai_messages(user.conversation_summary, history, user_text)

    client = get_openai_client()
    response = await client.responses.create(model=model, input=messages)
    answer = response.output_text.strip() if response.output_text else "Не удалось получить ответ модели."

    session.add(ChatMessage(user_id=user.id, role="user", content=user_text))
    session.add(ChatMessage(user_id=user.id, role="assistant", content=answer))
    await session.flush()

    await increment_usage(session, user.id)
    await session.commit()

    # Update message cache: append new turn, keep within limit
    limit = settings.recent_user_messages * 2
    updated = list(history) + [_Msg("user", user_text), _Msg("assistant", answer)]
    _cache_set_msgs(user.id, updated[-limit:])

    return ChatTurnResult(answer=answer)
