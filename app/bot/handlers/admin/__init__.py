from aiogram import Router

from app.bot.handlers.admin.filters import AdminFilter
from app.bot.handlers.admin import handlers_main, handlers_plans, handlers_users

router = Router(name="admin")

# Apply AdminFilter to every message and callback_query in this router tree.
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())

router.include_router(handlers_main.router)
router.include_router(handlers_plans.router)
router.include_router(handlers_users.router)
