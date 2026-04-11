from __future__ import annotations

import asyncio

from app.db.base import Base
from app.db.models import (  # noqa: F401
    ChatMessage,
    Payment,
    Plan,
    Subscription,
    UsageCounter,
    User,
)
from app.db.session import get_engine


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def main() -> None:
    asyncio.run(init_db())


if __name__ == "__main__":
    main()
