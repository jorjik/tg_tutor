from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="common")


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я GPT-ассистент с подпиской.\n\n"
        "Команды:\n"
        "/start — это сообщение\n"
        "/status — статус вашей подписки\n"
        "/subscribe — оформить подписку\n"
        "/reset — очистить память диалога\n"
        "/admin — панель администратора (только для разрешённых id)"
    )
