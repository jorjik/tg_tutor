from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatMessage, Payment, Plan, Subscription, UsageCounter, User


# ── Result dataclasses ───────────────────────────────────────────────────────

@dataclass(slots=True)
class AdminStats:
    total_users: int
    active_subscriptions: int
    total_revenue: Decimal


@dataclass(slots=True)
class UserRow:
    id: int
    telegram_id: int
    username: str | None
    sub_status: str | None
    sub_plan_name: str | None
    sub_ends_at: datetime | None


@dataclass(slots=True)
class UserDetail:
    id: int
    telegram_id: int
    username: str | None
    locale: str | None
    created_at: datetime
    message_count: int
    sub_status: str | None
    sub_plan_name: str | None
    sub_starts_at: datetime | None
    sub_ends_at: datetime | None
    total_requests: int


# ── Stats ────────────────────────────────────────────────────────────────────

async def get_admin_stats(session: AsyncSession) -> AdminStats:
    total_users = await session.scalar(select(func.count(User.id))) or 0

    active_subs = await session.scalar(
        select(func.count(Subscription.id)).where(
            Subscription.status == "active",
            Subscription.ends_at > func.now(),
        )
    ) or 0

    total_revenue = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.status == "succeeded"
        )
    ) or Decimal(0)

    return AdminStats(
        total_users=total_users,
        active_subscriptions=active_subs,
        total_revenue=Decimal(str(total_revenue)),
    )


# ── Plans ────────────────────────────────────────────────────────────────────

async def get_all_plans(session: AsyncSession) -> list[Plan]:
    result = await session.execute(
        select(Plan).order_by(Plan.sort_order.asc(), Plan.id.asc())
    )
    return list(result.scalars().all())


async def get_plan_by_id(session: AsyncSession, plan_id: int) -> Plan | None:
    return await session.get(Plan, plan_id)


_FIELD_TYPES: dict[str, str] = {
    "name": "str",
    "price": "decimal",
    "currency": "currency",
    "duration_days": "posint",
    "max_day": "nullable_int",
    "max_period": "nullable_int",
    # поддерживаем оба ключа: "openai_model" (wizard) и "model" (кнопки редактирования)
    "openai_model": "str",
    "model": "str",
    "sort_order": "nonneg_int",
    "stars_price": "nullable_stars",
}

_FIELD_ATTR: dict[str, str] = {
    "max_day": "max_requests_per_day",
    "max_period": "max_requests_per_period",
    "model": "openai_model",
    # "openai_model" → атрибут совпадает, но явно для ясности:
    "openai_model": "openai_model",
}


def _cast_field(field: str, raw: str) -> object:
    kind = _FIELD_TYPES[field]
    raw = raw.strip()
    if kind == "str":
        if not raw:
            raise ValueError("Значение не может быть пустым.")
        return raw
    if kind == "decimal":
        try:
            v = Decimal(raw)
        except Exception:
            raise ValueError("Введите число, например 299.00")
        if v <= 0:
            raise ValueError("Цена должна быть больше нуля.")
        return v
    if kind == "currency":
        if len(raw) != 3:
            raise ValueError("Валюта — 3 буквы (например RUB, USD).")
        return raw.upper()
    if kind == "posint":
        if not raw.isdigit() or int(raw) <= 0:
            raise ValueError("Введите целое число больше нуля.")
        return int(raw)
    if kind == "nullable_int":
        if raw in ("-", ""):
            return None
        if not raw.isdigit() or int(raw) <= 0:
            raise ValueError("Введите целое число > 0 или «-» чтобы убрать ограничение.")
        return int(raw)
    if kind == "nonneg_int":
        if not raw.isdigit():
            raise ValueError("Введите целое число ≥ 0.")
        return int(raw)
    if kind == "nullable_stars":
        if raw in ("-", "0", ""):
            return None
        if not raw.isdigit() or int(raw) <= 0:
            raise ValueError("Введите целое число Stars > 0 или «-» чтобы отключить.")
        return int(raw)
    raise ValueError(f"Неизвестное поле: {field}")


async def update_plan_field(
    session: AsyncSession, plan_id: int, field: str, raw_value: str
) -> Plan:
    plan = await session.get(Plan, plan_id)
    if plan is None:
        raise LookupError("Тариф не найден.")
    value = _cast_field(field, raw_value)
    attr = _FIELD_ATTR.get(field, field)
    setattr(plan, attr, value)
    await session.flush()
    await session.commit()
    return plan


async def toggle_plan_active(session: AsyncSession, plan_id: int) -> Plan:
    plan = await session.get(Plan, plan_id)
    if plan is None:
        raise LookupError("Тариф не найден.")
    plan.is_active = not plan.is_active
    await session.flush()
    await session.commit()
    return plan


async def create_plan(session: AsyncSession, **kwargs: object) -> Plan:
    plan = Plan(**kwargs)
    session.add(plan)
    await session.flush()
    await session.commit()
    await session.refresh(plan)
    return plan


async def delete_plan(session: AsyncSession, plan_id: int) -> None:
    active_count = await session.scalar(
        select(func.count(Subscription.id)).where(
            Subscription.plan_id == plan_id,
            Subscription.status == "active",
        )
    ) or 0
    if active_count > 0:
        raise ValueError(
            f"Тариф используется {active_count} активной(-ыми) подпиской(-ами). "
            "Сначала переведите пользователей на другой тариф."
        )
    plan = await session.get(Plan, plan_id)
    if plan is None:
        return
    await session.delete(plan)
    await session.commit()


# ── Users ────────────────────────────────────────────────────────────────────

async def get_users_page(
    session: AsyncSession, page: int, page_size: int = 8
) -> tuple[list[UserRow], int]:
    total = await session.scalar(select(func.count(User.id))) or 0

    # Subquery: latest subscription id per user
    latest_sub_id = (
        select(Subscription.id)
        .where(Subscription.user_id == User.id)
        .order_by(Subscription.starts_at.desc())
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )

    stmt = (
        select(
            User.id,
            User.telegram_id,
            User.username,
            Subscription.status.label("sub_status"),
            Plan.name.label("plan_name"),
            Subscription.ends_at.label("sub_ends_at"),
        )
        .outerjoin(Subscription, Subscription.id == latest_sub_id)
        .outerjoin(Plan, Plan.id == Subscription.plan_id)
        .order_by(User.created_at.desc())
        .limit(page_size)
        .offset(page * page_size)
    )

    rows = (await session.execute(stmt)).all()
    result = [
        UserRow(
            id=r.id,
            telegram_id=r.telegram_id,
            username=r.username,
            sub_status=r.sub_status,
            sub_plan_name=r.plan_name,
            sub_ends_at=r.sub_ends_at,
        )
        for r in rows
    ]
    return result, total


async def get_user_detail(session: AsyncSession, user_id: int) -> UserDetail | None:
    user = await session.get(User, user_id)
    if user is None:
        return None

    message_count = await session.scalar(
        select(func.count(ChatMessage.id)).where(ChatMessage.user_id == user_id)
    ) or 0

    total_requests = await session.scalar(
        select(func.coalesce(func.sum(UsageCounter.requests_count), 0)).where(
            UsageCounter.user_id == user_id
        )
    ) or 0

    latest_sub_row = (
        await session.execute(
            select(Subscription, Plan.name.label("plan_name"))
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.starts_at.desc())
            .limit(1)
        )
    ).first()

    sub_status = sub_plan_name = sub_starts_at = sub_ends_at = None
    if latest_sub_row:
        sub, plan_name = latest_sub_row[0], latest_sub_row[1]
        sub_status = sub.status
        sub_plan_name = plan_name
        sub_starts_at = sub.starts_at
        sub_ends_at = sub.ends_at

    return UserDetail(
        id=user.id,
        telegram_id=user.telegram_id,
        username=user.username,
        locale=user.locale,
        created_at=user.created_at,
        message_count=message_count,
        sub_status=sub_status,
        sub_plan_name=sub_plan_name,
        sub_starts_at=sub_starts_at,
        sub_ends_at=sub_ends_at,
        total_requests=int(total_requests),
    )
