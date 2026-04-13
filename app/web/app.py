from __future__ import annotations

import logging

from fastapi import FastAPI

from app.web.routes import webhooks

logger = logging.getLogger(__name__)

app = FastAPI(
    title="TG Tutor — Web Service",
    description="Вебхуки платёжного провайдера",
    docs_url="/docs",
    redoc_url=None,
)

app.include_router(webhooks.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
