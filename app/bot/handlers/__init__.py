from aiogram import Router

from app.bot.handlers import chat, common, stars, user
from app.bot.handlers.admin import router as admin_router

root_router = Router()
root_router.include_router(common.router)
root_router.include_router(admin_router)
root_router.include_router(user.router)
root_router.include_router(stars.router)  # до chat: F.successful_payment не должен попасть к ИИ
root_router.include_router(chat.router)
