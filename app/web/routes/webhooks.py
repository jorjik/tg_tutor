from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.config import get_settings
from app.services.payments import get_provider
from app.services.subscription_service import activate_subscription

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def webhook_stripe(request: Request) -> Response:
    settings = get_settings()
    if settings.payment_provider != "stripe":
        raise HTTPException(status_code=404)

    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    provider = get_provider(settings)
    try:
        result = await provider.parse_webhook(body, headers)
    except ValueError as exc:
        logger.warning("Stripe webhook error: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if result and result.succeeded:
        await activate_subscription(
            telegram_id=result.telegram_id,
            plan_id=result.plan_id,
            provider="stripe",
            provider_payment_id=result.provider_payment_id,
            amount=result.amount,
            currency=result.currency,
            raw_payload={},
        )

    return Response(status_code=200)


@router.post("/yookassa")
async def webhook_yookassa(request: Request) -> Response:
    settings = get_settings()
    if settings.payment_provider != "yookassa":
        raise HTTPException(status_code=404)

    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    provider = get_provider(settings)
    try:
        result = await provider.parse_webhook(body, headers)
    except ValueError as exc:
        logger.warning("YooKassa webhook error: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if result and result.succeeded:
        await activate_subscription(
            telegram_id=result.telegram_id,
            plan_id=result.plan_id,
            provider="yookassa",
            provider_payment_id=result.provider_payment_id,
            amount=result.amount,
            currency=result.currency,
            raw_payload={},
        )

    return Response(status_code=200)
