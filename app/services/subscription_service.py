from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Payment,
    PaymentStatus,
    Plan,
    Subscription,
    SubscriptionStatus,
    UsageCounter,
    User,
)

logger = logging.getLogger(__name__)

# ── Subscription TTL cache ────────────────────────────────────────────────────
# Keyed by internal DB user_id. Stores (ActiveSubscription | None, monotonic_ts).
_SUB_TTL: Final[float] = 60.0
_sub_cache: dict[int, tuple[ActiveSubscription | None, float]] = {}
_MISS = object()


def _cache_get_sub(user_id: int) -> object:
    entry = _sub_cache.get(user_id)
    if entry is None:
        return _MISS
    sub, ts = entry
    if time.monotonic() - ts > _SUB_TTL:
        _sub_cache.pop(user_id, None)
        return _MISS
    return sub


def _cache_set_sub(user_id: int, sub: ActiveSubscription | None) -> None:
    _sub_cache[user_id] = (sub, time.monotonic())


def invalidate_subscription_cache(user_id: int) -> None:
    """Вызывать при активации/смене подписки."""
    _sub_cache.pop(user_id, None)


@dataclass(slots=True)
class ActiveSubscription:
    subscription: Subscription
    plan: Plan


async def get_active_subscription(
    session: AsyncSession, user_id: int
) -> ActiveSubscription | None:
    row = (
        await session.execute(
            select(Subscription, Plan)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.ends_at > func.now(),
            )
            .order_by(Subscription.ends_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return ActiveSubscription(subscription=row[0], plan=row[1])


def _day_start_utc() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def get_usage_today(session: AsyncSession, user_id: int) -> int:
    today = _day_start_utc()
    result = await session.scalar(
        select(UsageCounter.requests_count).where(
            UsageCounter.user_id == user_id,
            UsageCounter.period_start == today,
        )
    )
    return int(result) if result else 0


async def get_usage_since(
    session: AsyncSession, user_id: int, since: datetime
) -> int:
    result = await session.scalar(
        select(func.coalesce(func.sum(UsageCounter.requests_count), 0)).where(
            UsageCounter.user_id == user_id,
            UsageCounter.period_start >= since,
        )
    )
    return int(result) if result else 0


async def check_limits(
    session: AsyncSession,
    user_id: int,
    active_sub: ActiveSubscription,
) -> tuple[bool, str]:
    """Returns (is_allowed, reason_if_denied)."""
    plan = active_sub.plan

    if plan.max_requests_per_day is not None:
        today_count = await get_usage_today(session, user_id)
        if today_count >= plan.max_requests_per_day:
            return False, (
                f"Суточный лимит запросов исчерпан "
                f"({plan.max_requests_per_day} запр./день). "
                "Попробуйте завтра."
            )

    if plan.max_requests_per_period is not None:
        period_count = await get_usage_since(
            session, user_id, active_sub.subscription.starts_at
        )
        if period_count >= plan.max_requests_per_period:
            return False, (
                f"Лимит запросов за период подписки исчерпан "
                f"({plan.max_requests_per_period} запр./период). "
                "Оформите новую подписку с помощью /subscribe."
            )

    return True, ""


async def increment_usage(session: AsyncSession, user_id: int) -> None:
    """Атомарно увеличивает счётчик запросов за сегодня на 1."""
    today = _day_start_utc()
    stmt = (
        pg_insert(UsageCounter)
        .values(user_id=user_id, period_start=today, requests_count=1)
        .on_conflict_do_update(
            constraint="uq_usage_counters_user_period",
            set_={"requests_count": UsageCounter.requests_count + 1},
        )
    )
    await session.execute(stmt)


async def activate_subscription(
    *,
    telegram_id: int,
    plan_id: int,
    provider: str,
    provider_payment_id: str,
    amount: Decimal,
    currency: str,
    raw_payload: dict,
) -> None:
    """Идемпотентно фиксирует платёж и создаёт/продлевает подписку."""
    from app.db.session import AsyncSessionLocal
    from app.services.admin_service import get_plan_by_id

    async with AsyncSessionLocal() as session:
        existing = await session.scalar(
            select(Payment).where(
                Payment.provider == provider,
                Payment.provider_payment_id == provider_payment_id,
                Payment.status == PaymentStatus.SUCCEEDED,
            )
        )
        if existing:
            logger.info("activate_subscription: платёж %s/%s уже обработан", provider, provider_payment_id)
            return

        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            logger.warning("activate_subscription: пользователь telegram_id=%d не найден", telegram_id)
            return

        plan = await get_plan_by_id(session, plan_id)
        if plan is None:
            logger.warning("activate_subscription: тариф plan_id=%d не найден", plan_id)
            return

        session.add(Payment(
            user_id=user.id,
            plan_id=plan.id,
            provider=provider,
            provider_payment_id=provider_payment_id,
            amount=amount,
            currency=currency,
            status=PaymentStatus.SUCCEEDED,
            raw_payload=raw_payload,
        ))

        now = datetime.now(UTC)
        active_sub = await session.scalar(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.ends_at > now,
            )
        )
        if active_sub and active_sub.plan_id == plan.id:
            active_sub.ends_at += timedelta(days=plan.duration_days)
        else:
            if active_sub:
                active_sub.status = SubscriptionStatus.EXPIRED
            session.add(Subscription(
                user_id=user.id,
                plan_id=plan.id,
                starts_at=now,
                ends_at=now + timedelta(days=plan.duration_days),
                status=SubscriptionStatus.ACTIVE,
            ))

        await session.commit()
        invalidate_subscription_cache(user.id)
        logger.info(
            "activate_subscription: подписка активирована user=%d plan=%d provider=%s",
            user.id, plan.id, provider,
        )
