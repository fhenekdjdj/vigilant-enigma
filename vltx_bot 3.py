"""
VLTX — Telegram-бот продажи подарков за RUB или звёзды.

Запуск:
    pip install "aiogram>=3.7"
    export BOT_TOKEN="123:ABC..."
    export ADMIN_ID="123456789"      # ID администратора, куда приходят заявки
    python vltx_bot.py
"""

import asyncio
import html
import logging
import os
import re
import secrets
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

SUPPORT_USERNAME = "@VLTXListBank"
SUPPORT_URL = "https://t.me/VLTXListBank"

GIFTS = ["Parking Lot", "Phosphorus", "X-Ray"]
PAYOUT = {"stars": 2550, "rub": 3100}
CURRENCY_LABEL = {"stars": "звёзд", "rub": "RUB"}

WELCOME_TEXT = (
    "Добро пожаловать 👋\n\n"
    "💼 VLTX - Мы специализированный сервис по автоматической покупки подарков "
    "и обеспечению безопасности вне биржевых сделок.\n\n"
    "✨ Автоматизированый алгоритм исполнения.\n"
    "⚡️ Скорость и автоматизация.\n"
    "💳 Удобный и быстрый вывод средств.\n\n"
    "• Режим работы: 24/7\n"
    f"• Техническая поддержка: {SUPPORT_URL}"
)

router = Router()


class Sell(StatesGroup):
    card = State()
    username = State()


class Admin(StatesGroup):
    photo = State()


# ───────────────────────── клавиатуры ─────────────────────────

def kb(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t, callback_data=d) for t, d in row]
            for row in rows
        ]
    )


def main_kb() -> InlineKeyboardMarkup:
    return kb([("Продать подарок", "sell")])


def key_kb() -> InlineKeyboardMarkup:
    return kb([("Input Key", "key")], [("⬅️ Назад", "home")])


def gifts_kb() -> InlineKeyboardMarkup:
    rows = [[(name, f"gift:{i}")] for i, name in enumerate(GIFTS)]
    rows.append([("⬅️ Назад", "sell")])
    return kb(*rows)


def currency_kb() -> InlineKeyboardMarkup:
    return kb(
        [("Продать в звездах", "cur:stars")],
        [("Продать в RUB", "cur:rub")],
        [("⬅️ Назад", "key")],
    )


# ───────────────────────── вспомогательное ─────────────────────────

def offer_text(data: dict) -> str:
    cur = data["currency"]
    amount = PAYOUT[cur]
    requisites = (
        f"Карта: <code>{html.escape(data['requisites'])}</code>"
        if cur == "rub"
        else f"Юзернейм для выплаты: {html.escape(data['requisites'])}"
    )
    return (
        f"🎁 Подарок: <b>{html.escape(data['gift'])}</b>\n"
        f"{requisites}\n\n"
        f"💰 Вы получите: <b>{amount} {CURRENCY_LABEL[cur]}</b>\n\n"
        "Выплата производится после того, как поддержка проверит получение подарка."
    )


def offer_kb() -> InlineKeyboardMarkup:
    return kb([("✅ Подтвердить продажу", "confirm")], [("❌ Отмена", "home")])


# ───────────────────────── пользовательский поток ─────────────────────────

MENU_IMAGE = Path(__file__).with_name("menu.jpg")  # запасная картинка рядом с ботом
MENU_ID_FILE = Path(__file__).with_name("menu_photo.txt")  # сюда пишет /setphoto
NO_PHOTO = "-"  # метка «картинка отключена»


def read_menu_photo() -> str | None:
    """file_id картинки меню: файл от /setphoto, затем переменная MENU_PHOTO_ID."""
    try:
        value = MENU_ID_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    return value or os.getenv("MENU_PHOTO_ID") or None


async def send_menu(message: Message):
    """Главное меню: картинка + приветствие в подписи + кнопка."""
    stored = read_menu_photo()
    if stored == NO_PHOTO:
        photo = None
    elif stored:
        photo = stored
    elif MENU_IMAGE.exists():
        photo = FSInputFile(MENU_IMAGE)
    else:
        photo = None

    if photo:
        try:
            await message.answer_photo(
                photo, caption=WELCOME_TEXT, reply_markup=main_kb()
            )
            return
        except Exception:
            logging.exception("Не удалось отправить картинку меню")
    await message.answer(WELCOME_TEXT, reply_markup=main_kb())


async def safe_delete(message: Message):
    try:
        await message.delete()
    except Exception:
        pass


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await send_menu(message)


@router.callback_query(F.data == "home")
async def cb_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_delete(call.message)
    await send_menu(call.message)
    await call.answer()


@router.callback_query(F.data == "sell")
async def cb_sell(call: CallbackQuery, state: FSMContext):
    await state.clear()
    text = "Выберите какой подарок хотите продать?"
    if call.message.photo:  # из главного меню (фото) текст не отредактировать
        await safe_delete(call.message)
        await call.message.answer(text, reply_markup=key_kb())
    else:
        await call.message.edit_text(text, reply_markup=key_kb())
    await call.answer()


@router.callback_query(F.data == "key")
async def cb_key(call: CallbackQuery):
    await call.message.edit_text(
        "Выберите какой подарок хотите продать?", reply_markup=gifts_kb()
    )
    await call.answer()


@router.callback_query(F.data.startswith("gift:"))
async def cb_gift(call: CallbackQuery, state: FSMContext):
    idx = int(call.data.split(":")[1])
    if idx not in range(len(GIFTS)):
        return await call.answer()
    await state.update_data(gift=GIFTS[idx])
    await call.message.edit_text(
        f"🎁 Подарок: <b>{GIFTS[idx]}</b>\n\nВыберите, в чём хотите получить выплату:",
        reply_markup=currency_kb(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("cur:"))
async def cb_currency(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "gift" not in data:
        await call.answer("Сессия устарела, начните заново: /start", show_alert=True)
        return

    cur = call.data.split(":")[1]
    await state.update_data(currency=cur)

    if cur == "rub":
        await state.set_state(Sell.card)
        await call.message.edit_text(
            "💳 Введите номер банковской карты, на которую получите выплату "
            "(16–19 цифр):"
        )
    else:
        username = call.from_user.username
        if username:
            await state.update_data(requisites=f"@{username}")
            data = await state.get_data()
            await call.message.edit_text(offer_text(data), reply_markup=offer_kb())
        else:
            await state.set_state(Sell.username)
            await call.message.edit_text(
                "У вас не указан юзернейм в Telegram.\n"
                "Введите юзернейм (например, @username), на который отправить звёзды:"
            )
    await call.answer()


@router.message(Sell.card)
async def msg_card(message: Message, state: FSMContext):
    number = re.sub(r"[\s-]", "", message.text or "")
    if not (number.isascii() and number.isdigit() and 16 <= len(number) <= 19):
        await message.answer("Номер карты некорректен. Проверьте и введите ещё раз:")
        return

    await state.update_data(requisites=number)
    await state.set_state(None)
    try:
        await message.delete()  # не оставляем номер карты в чате
    except Exception:
        pass
    data = await state.get_data()
    await message.answer(offer_text(data), reply_markup=offer_kb())


@router.message(Sell.username)
async def msg_username(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not re.fullmatch(r"@?[A-Za-z0-9_]{5,32}", text):
        await message.answer("Юзернейм некорректен. Пример: @username. Введите ещё раз:")
        return

    await state.update_data(requisites="@" + text.lstrip("@"))
    await state.set_state(None)
    data = await state.get_data()
    await message.answer(offer_text(data), reply_markup=offer_kb())


@router.callback_query(F.data == "confirm")
async def cb_confirm(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not {"gift", "currency", "requisites"} <= data.keys():
        await call.answer("Сессия устарела, начните заново: /start", show_alert=True)
        return

    await call.message.edit_text(
        f"Для получения выплаты передайте подарок <b>{html.escape(data['gift'])}</b> "
        f"поддержке — {SUPPORT_USERNAME}\n\n"
        "После того как подарок будет передан, нажмите «Подтверждение передачи».\n"
        "Выплата будет произведена после проверки получения подарка.",
        reply_markup=kb([("📤 Подтверждение передачи", "sent")], [("❌ Отмена", "home")]),
    )
    await call.answer()


@router.callback_query(F.data == "sent")
async def cb_sent(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    if not {"gift", "currency", "requisites"} <= data.keys():
        await call.answer("Заявка уже отправлена или устарела.", show_alert=True)
        return

    order_id = secrets.token_hex(3).upper()
    cur = data["currency"]
    user = call.from_user
    requisites_line = (
        f"💳 Карта: <code>{html.escape(data['requisites'])}</code>"
        if cur == "rub"
        else f"⭐️ Юзернейм для выплаты: {html.escape(data['requisites'])}"
    )

    admin_text = (
        f"🆕 <b>Заявка #{order_id}</b>\n"
        f"🕒 {datetime.now():%d.%m.%Y %H:%M:%S}\n\n"
        f"👤 Пользователь: {html.escape(user.full_name)}"
        f"{' (@' + user.username + ')' if user.username else ''}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"🎁 Подарок: <b>{html.escape(data['gift'])}</b>\n"
        f"💰 Сумма к выплате: <b>{PAYOUT[cur]} {CURRENCY_LABEL[cur]}</b>\n"
        f"{requisites_line}\n\n"
        "Статус: ожидает проверки получения подарка"
    )
    await bot.send_message(
        ADMIN_ID,
        admin_text,
        reply_markup=kb([("✅ Подарок получен, выплачено", f"paid:{user.id}:{order_id}")]),
    )

    await state.clear()  # реквизиты у бота не хранятся
    await call.message.edit_text(
        f"✅ Заявка <b>#{order_id}</b> отправлена.\n\n"
        "Как только поддержка проверит получение подарка, вы получите выплату "
        "и уведомление здесь.",
        reply_markup=kb([("🏠 В начало", "home")]),
    )
    await call.answer()


# ───────────────────────── действия администратора ─────────────────────────

@router.callback_query(F.data.startswith("paid:"))
async def cb_paid(call: CallbackQuery, bot: Bot):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("Нет доступа.", show_alert=True)

    _, user_id, order_id = call.data.split(":")
    await call.message.edit_text(
        call.message.html_text.replace(
            "Статус: ожидает проверки получения подарка", "Статус: ✅ выплачено"
        ),
        reply_markup=None,
    )
    try:
        await bot.send_message(
            int(user_id),
            f"💸 Заявка <b>#{order_id}</b>: подарок получен, выплата произведена. Спасибо!",
        )
    except Exception:
        logging.warning("Не удалось уведомить пользователя %s", user_id)
    await call.answer("Готово")


@router.message(Command("setphoto"), F.from_user.id == ADMIN_ID)
async def cmd_setphoto(message: Message, state: FSMContext):
    await state.set_state(Admin.photo)
    await message.answer(
        "Отправьте картинку для главного меню (именно как фото, не как файл).\n"
        "Отмена: /cancel"
    )


@router.message(Command("cancel"), F.from_user.id == ADMIN_ID)
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.")


@router.message(Admin.photo, F.photo, F.from_user.id == ADMIN_ID)
@router.message(F.photo, F.caption.startswith("/setphoto"), F.from_user.id == ADMIN_ID)
async def msg_setphoto(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.clear()
    try:
        MENU_ID_FILE.write_text(file_id, encoding="utf-8")
    except OSError:
        await message.answer(
            "Не удалось сохранить картинку на диск хостинга.\n"
            f"Добавьте этот file_id в переменную окружения MENU_PHOTO_ID:\n<code>{file_id}</code>"
        )
        return
    await message.answer("✅ Картинка обновлена. Так теперь выглядит главное меню:")
    await send_menu(message)
    await message.answer(
        "Если после обновления или перезапуска на хостинге картинка пропадёт, "
        f"добавьте этот file_id в переменную окружения MENU_PHOTO_ID:\n<code>{file_id}</code>"
    )


@router.message(Admin.photo, F.from_user.id == ADMIN_ID)
async def msg_setphoto_wrong(message: Message):
    await message.answer("Нужна картинка, отправленная как фото. Или /cancel для отмены.")


@router.message(Command("delphoto"), F.from_user.id == ADMIN_ID)
async def cmd_delphoto(message: Message):
    try:
        MENU_ID_FILE.write_text(NO_PHOTO, encoding="utf-8")
    except OSError:
        await message.answer("Не удалось сохранить настройку на диск хостинга.")
        return
    await message.answer(
        "Картинка убрана, главное меню теперь только текстом.\nВернуть: /setphoto"
    )


# ───────────────────────── запуск ─────────────────────────

async def main():
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN or not ADMIN_ID:
        raise SystemExit("Задайте переменные окружения BOT_TOKEN и ADMIN_ID")

    bot = Bot(
        BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML, link_preview_is_disabled=True
        ),
    )
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
