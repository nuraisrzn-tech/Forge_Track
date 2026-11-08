"""
Forge Track — Telegram-бот (аналог сайта https://folixmibombo.github.io/)

Запуск:
    pip install -r requirements.txt
    set BOT_TOKEN=ваш_токен        (Windows, cmd)
    $env:BOT_TOKEN="ваш_токен"     (Windows, PowerShell)
    export BOT_TOKEN=ваш_токен     (Linux / macOS)
    python bot.py

Токен можно положить и в файл .env рядом с bot.py:  BOT_TOKEN=...
"""

import asyncio
import logging
import math
import os
import re

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# ДАННЫЕ (меняй здесь)
# ---------------------------------------------------------------------------

# Страны и города для выбора направления.
COUNTRIES = {
    "kz": ("🇰🇿 Казахстан", ["Алматы", "Астана", "Шымкент", "Караганда"]),
    "ru": ("🇷🇺 Россия", ["Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург"]),
    "cn": ("🇨🇳 Китай", ["Пекин", "Шанхай", "Гуанчжоу", "Урумчи"]),
    "tr": ("🇹🇷 Турция", ["Стамбул", "Анкара", "Измир"]),
    "kg": ("🇰🇬 Кыргызстан", ["Бишкек", "Ош"]),
    "uz": ("🇺🇿 Узбекистан", ["Ташкент", "Самарканд"]),
    "de": ("🇩🇪 Германия", ["Берлин", "Мюнхен", "Франкфурт"]),
    "us": ("🇺🇸 США", ["Нью-Йорк", "Лос-Анджелес", "Чикаго"]),
}

# Перевозчики. ВАЖНО: список стран (countries) и тарифы (base / per_kg) —
# ПРИМЕРНЫЕ тестовые значения. Замени на подтверждённые данные перевозчиков.
CARRIERS = {
    "jet": {
        "name": "Jet Logistic",
        "site": "https://jet.com.kz/",
        "support": "https://jet.com.kz/%D0%BA%D0%BE%D0%BD%D1%82%D0%B0%D0%BA%D1%82%D1%8B.html",
        "faq": "https://jet.com.kz/%D0%B2%D0%BE%D0%BF%D1%80%D0%BE%D1%81%D1%8B-%D0%B8-%D0%BE%D1%82%D0%B2%D0%B5%D1%82%D1%8B.html",
        "countries": {"kz", "ru", "cn", "tr", "kg", "uz"},
        "base": 2500,
        "per_kg": 1800,
        "about": "Контакты офисов и складов, call-центр, онлайн-заявка и ответы на частые вопросы — на официальном сайте.",
    },
    "kaz": {
        "name": "Казпочта",
        "site": "https://post.kz/",
        "support": "https://post.kz/",
        "faq": "https://qazpost.kz/ru",
        "countries": {"kz", "ru", "cn", "tr", "kg", "uz", "de", "us"},
        "base": 1800,
        "per_kg": 1400,
        "about": "Контакт-центр, чат и раздел «Помощь» находятся на официальном сайте. Там же можно найти ближайшее отделение.",
    },
    "cdek": {
        "name": "CDEK",
        "site": "https://cdek.kz/ru/",
        "support": "https://cdek.kz/ru/",
        "faq": None,
        "countries": {"kz", "ru", "cn", "kg", "uz", "tr"},
        "base": 3200,
        "per_kg": 2100,
        "about": "Контакты, онлайн-чат и справочная информация CDEK Казахстан — на официальном сайте.",
    },
}

CARGO_TYPES = {
    "doc": ("📄 Документы", 0.8),
    "goods": ("📦 Обычный груз", 1.0),
    "fragile": ("🥂 Хрупкий груз", 1.3),
}

OFFICIAL_DOC_LINKS = [
    ("Jet Logistic — документы", "https://jet.com.kz/%D0%B4%D0%BE%D0%BA%D1%83%D0%BC%D0%B5%D0%BD%D1%82%D1%8B.html"),
    ("Казпочта — виды отправлений", "https://qazpost.kz/ru/calculator"),
    ("CDEK — тарифы и условия", "https://cdek.kz/ru/online-stores/tariffs/"),
    ("КГД РК — CN 22 / CN 23", "https://kgd.gov.kz/en/node/75758"),
]

MAX_WEIGHT = 100  # кг
MAX_SIDE = 300  # см

# ---------------------------------------------------------------------------
# Вспомогательное
# ---------------------------------------------------------------------------

router = Router()


def menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🧭 Выбор направления", callback_data="dir")
    b.button(text="🧮 Калькулятор доставки", callback_data="calc")
    b.button(text="📍 Отслеживание посылки", callback_data="track")
    b.button(text="📋 Необходимые документы", callback_data="docs")
    b.button(text="🛟 Техническая поддержка", callback_data="support")
    b.adjust(1)
    return b.as_markup()


def choice_kb(items, back="menu", width=1, extra_urls=None) -> InlineKeyboardMarkup:
    """items: [(text, callback_data)]. extra_urls: [(text, url)]."""
    b = InlineKeyboardBuilder()
    for text, data in items:
        b.button(text=text, callback_data=data)
    b.adjust(width)
    for text, url in extra_urls or []:
        b.row(InlineKeyboardButton(text=text, url=url))
    nav = [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]
    if back and back != "menu":
        nav.insert(0, InlineKeyboardButton(text="◀️ Назад", callback_data=back))
    b.row(*nav)
    return b.as_markup()


async def show(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None):
    """Редактирует сообщение с кнопкой, а если нельзя — отправляет новое."""
    try:
        await cb.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=markup, disable_web_page_preview=True)
    await cb.answer()


def parse_number(text: str) -> float | None:
    try:
        return float(text.strip().replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def money(x: float) -> str:
    return f"{int(round(x)):,}".replace(",", " ") + " ₸"


WELCOME = (
    "<b>Forge Track</b> — международная доставка стала проще 🚚\n\n"
    "Сравнивайте логистические компании, рассчитывайте стоимость и отслеживайте "
    "отправления через Казахстан: <b>Jet Logistic</b>, <b>Казпочта</b> и <b>CDEK</b>.\n\n"
    "Выберите раздел:"
)

DATA_NOTE = (
    "ℹ️ <i>Данные в этой версии (MVP): расчёты — демонстрационные, реальные тарифы "
    "перевозчиков можно получить только через их официальный API. Перед отправкой "
    "уточняйте условия на сайте компании.</i>"
)

# ---------------------------------------------------------------------------
# Старт и меню
# ---------------------------------------------------------------------------


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(WELCOME, reply_markup=menu_kb())


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Команды:\n/start или /menu — главное меню\n/cancel — отменить текущее действие\n\n" + DATA_NOTE
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=menu_kb())


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(cb, WELCOME, menu_kb())


# ---------------------------------------------------------------------------
# 1. Выбор направления (5 шагов)
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "dir")
async def dir_start(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    items = [(name, f"dir_oc:{code}") for code, (name, _) in COUNTRIES.items()]
    await show(cb, "<b>Шаг 1 из 5.</b> Страна отправления:", choice_kb(items, width=2))


@router.callback_query(F.data.startswith("dir_oc:"))
async def dir_origin_country(cb: CallbackQuery, state: FSMContext):
    code = cb.data.split(":")[1]
    await state.update_data(o_c=code)
    cities = COUNTRIES[code][1]
    items = [(c, f"dir_oi:{i}") for i, c in enumerate(cities)]
    await show(cb, f"<b>Шаг 2 из 5.</b> Город отправления ({COUNTRIES[code][0]}):", choice_kb(items, back="dir", width=2))


@router.callback_query(F.data.startswith("dir_oi:"))
async def dir_origin_city(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "o_c" not in data:
        return await show(cb, "Сессия устарела. Начните заново.", choice_kb([("Начать", "dir")]))
    idx = int(cb.data.split(":")[1])
    await state.update_data(o_city=COUNTRIES[data["o_c"]][1][idx])
    items = [(n, f"dir_dc:{c}") for c, (n, _) in COUNTRIES.items() if c != data["o_c"]]
    await show(cb, "<b>Шаг 3 из 5.</b> Страна назначения:", choice_kb(items, back=f"dir_oc:{data['o_c']}", width=2))


@router.callback_query(F.data.startswith("dir_dc:"))
async def dir_dest_country(cb: CallbackQuery, state: FSMContext):
    code = cb.data.split(":")[1]
    await state.update_data(d_c=code)
    cities = COUNTRIES[code][1]
    items = [(c, f"dir_di:{i}") for i, c in enumerate(cities)]
    await show(cb, f"<b>Шаг 4 из 5.</b> Город назначения ({COUNTRIES[code][0]}):", choice_kb(items, back="dir", width=2))


@router.callback_query(F.data.startswith("dir_di:"))
async def dir_result(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "o_c" not in data or "d_c" not in data:
        return await show(cb, "Сессия устарела. Начните заново.", choice_kb([("Начать", "dir")]))
    idx = int(cb.data.split(":")[1])
    d_city = COUNTRIES[data["d_c"]][1][idx]
    o_c, d_c = data["o_c"], data["d_c"]

    available = [k for k, c in CARRIERS.items() if o_c in c["countries"] and d_c in c["countries"]]
    route = f"{data['o_city']} ({COUNTRIES[o_c][0]}) → {d_city} ({COUNTRIES[d_c][0]})"
    if available:
        lines = "\n".join(f"✅ <b>{CARRIERS[k]['name']}</b>" for k in available)
        text = f"<b>Шаг 5 из 5.</b> Маршрут:\n{route}\n\nДоступные перевозчики:\n{lines}\n\n{DATA_NOTE}"
        items = [(f"🧮 Рассчитать: {CARRIERS[k]['name']}", f"calc_c:{k}") for k in available]
    else:
        text = f"Маршрут:\n{route}\n\nК сожалению, подтверждённых перевозчиков для этого направления нет."
        items = []
    await show(cb, text, choice_kb(items, back="dir"))


# ---------------------------------------------------------------------------
# 2. Калькулятор доставки
# ---------------------------------------------------------------------------


class Calc(StatesGroup):
    weight = State()
    length = State()
    width = State()
    height = State()


@router.callback_query(F.data == "calc")
async def calc_start(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    items = [(c["name"], f"calc_c:{k}") for k, c in CARRIERS.items()]
    await show(cb, "<b>Калькулятор доставки</b>\nВыберите компанию:", choice_kb(items))


@router.callback_query(F.data.startswith("calc_c:"))
async def calc_carrier(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":")[1]
    await state.set_state(Calc.weight)
    await state.update_data(carrier=key)
    await show(
        cb,
        f"<b>{CARRIERS[key]['name']}</b>\nВведите вес посылки в кг (например, 2.5).\n/cancel — отмена",
        choice_kb([], back="calc"),
    )


async def _ask_number(message: Message, state: FSMContext, field: str, limit: float, next_state, prompt: str):
    value = parse_number(message.text or "")
    if value is None or value <= 0 or value > limit:
        return await message.answer(f"Введите число больше 0 и не больше {limit:g}.")
    await state.update_data(**{field: value})
    await state.set_state(next_state)
    await message.answer(prompt)


@router.message(Calc.weight)
async def calc_weight(message: Message, state: FSMContext):
    await _ask_number(message, state, "weight", MAX_WEIGHT, Calc.length, "Длина, см:")


@router.message(Calc.length)
async def calc_length(message: Message, state: FSMContext):
    await _ask_number(message, state, "length", MAX_SIDE, Calc.width, "Ширина, см:")


@router.message(Calc.width)
async def calc_width(message: Message, state: FSMContext):
    await _ask_number(message, state, "width", MAX_SIDE, Calc.height, "Высота, см:")


@router.message(Calc.height)
async def calc_height(message: Message, state: FSMContext):
    value = parse_number(message.text or "")
    if value is None or value <= 0 or value > MAX_SIDE:
        return await message.answer(f"Введите число больше 0 и не больше {MAX_SIDE}.")
    await state.update_data(height=value)
    items = [(name, f"calc_t:{k}") for k, (name, _) in CARGO_TYPES.items()]
    await message.answer("Тип груза:", reply_markup=choice_kb(items, width=1))


@router.callback_query(F.data.startswith("calc_t:"))
async def calc_result(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    need = {"carrier", "weight", "length", "width", "height"}
    if not need <= data.keys():
        return await show(cb, "Сессия устарела. Начните расчёт заново.", choice_kb([("Начать", "calc")]))

    carrier = CARRIERS[data["carrier"]]
    cargo_name, mult = CARGO_TYPES[cb.data.split(":")[1]]

    volumetric = data["length"] * data["width"] * data["height"] / 5000
    billable = math.ceil(max(data["weight"], volumetric) * 2) / 2  # округление до 0.5 кг
    price = (carrier["base"] + carrier["per_kg"] * billable) * mult

    text = (
        f"<b>Демонстрационный расчёт — {carrier['name']}</b>\n\n"
        f"Вес: {data['weight']:g} кг\n"
        f"Габариты: {data['length']:g}×{data['width']:g}×{data['height']:g} см\n"
        f"Объёмный вес: {volumetric:.2f} кг\n"
        f"Расчётный вес: {billable:g} кг\n"
        f"Тип груза: {cargo_name}\n\n"
        f"💰 Предварительная цена: <b>{money(price)}</b>\n\n{DATA_NOTE}"
    )
    await state.clear()
    items = [("🔁 Новый расчёт", "calc")]
    await show(cb, text, choice_kb(items, extra_urls=[(f"Сайт {carrier['name']}", carrier["site"])]))


# ---------------------------------------------------------------------------
# 3. Отслеживание посылки
# ---------------------------------------------------------------------------


class Track(StatesGroup):
    number = State()


@router.callback_query(F.data == "track")
async def track_start(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    items = [(c["name"], f"trk_c:{k}") for k, c in CARRIERS.items()]
    await show(cb, "<b>Отслеживание посылки</b>\nВыберите логистическую компанию:", choice_kb(items))


@router.callback_query(F.data.startswith("trk_c:"))
async def track_carrier(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":")[1]
    await state.set_state(Track.number)
    await state.update_data(carrier=key)
    await show(
        cb,
        f"<b>{CARRIERS[key]['name']}</b>\nВведите трек-номер.\n/cancel — отмена",
        choice_kb([], back="track"),
    )


@router.message(Track.number)
async def track_number(message: Message, state: FSMContext):
    number = (message.text or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9\-]{6,30}", number):
        return await message.answer("Трек-номер: 6–30 символов, только латиница, цифры и дефис. Попробуйте ещё раз.")
    carrier = CARRIERS[(await state.get_data())["carrier"]]
    await state.clear()
    await message.answer(
        f"Трек-номер: <code>{number}</code>\nКомпания: <b>{carrier['name']}</b>\n\n"
        "Мы не показываем выдуманные статусы: реальные данные появятся после подключения API "
        "перевозчика. Пока проверьте посылку на официальной странице.",
        reply_markup=choice_kb(
            [("📍 Отследить другую", "track")],
            extra_urls=[(f"Официальная страница {carrier['name']}", carrier["site"])],
        ),
    )


# ---------------------------------------------------------------------------
# 4. Необходимые документы
# ---------------------------------------------------------------------------

SENDER = {"fl": "Физическое лицо", "ul": "Юридическое лицо"}
KIND = {"lich": "Личная посылка", "com": "Коммерческий груз"}


def build_checklist(country: str, sender: str, kind: str) -> list[str]:
    items = ["Точные данные получателя: ФИО/название, адрес, телефон"]
    if sender == "fl":
        items.append("Документ, удостоверяющий личность отправителя")
    else:
        items += ["Реквизиты компании (БИН, адрес, контакты)", "Договор с перевозчиком"]
    items.append("Опись вложения (на английском или языке страны назначения)")
    if kind == "lich":
        items.append("Таможенная декларация CN 22 / CN 23 (для международных почтовых отправлений)")
    else:
        items += [
            "Коммерческий инвойс",
            "Контракт / договор поставки",
            "Упаковочный лист",
            "Код ТН ВЭД для каждого вида товара",
            "Сертификаты и разрешения на товар (если требуются)",
        ]
    items += [
        "Проверка перечня запрещённых к пересылке предметов",
        f"Проверка ограничений и пошлин страны назначения: {COUNTRIES[country][0]}",
    ]
    return items


def checklist_kb(items: list[str], done: set[int]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i, text in enumerate(items):
        mark = "✅" if i in done else "⬜"
        short = text if len(text) <= 48 else text[:45] + "…"
        b.button(text=f"{mark} {short}", callback_data=f"doc_x:{i}")
    b.adjust(1)
    b.row(InlineKeyboardButton(text="🔄 Сбросить отметки", callback_data="doc_reset"))
    for title, url in OFFICIAL_DOC_LINKS:
        b.row(InlineKeyboardButton(text=f"🔗 {title}", url=url))
    b.row(InlineKeyboardButton(text="⬅️ В меню", callback_data="menu"))
    return b.as_markup()


def checklist_text(items: list[str], done: set[int], country: str, sender: str, kind: str) -> str:
    lines = "\n".join(f"{'✅' if i in done else '⬜'} {t}" for i, t in enumerate(items))
    return (
        f"<b>Чек-лист документов</b>\n{COUNTRIES[country][0]} · {SENDER[sender]} · {KIND[kind]}\n\n"
        f"{lines}\n\nГотово: {len(done)} из {len(items)}\n\n"
        "<i>Перечень предварительный. Окончательные требования зависят от страны, вида груза, "
        "статуса отправителя и правил перевозчика — уточните их перед отправкой.</i>"
    )


@router.callback_query(F.data == "docs")
async def docs_start(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    items = [(n, f"doc_c:{c}") for c, (n, _) in COUNTRIES.items()]
    await show(cb, "<b>Необходимые документы</b>\nСтрана назначения:", choice_kb(items, width=2))


@router.callback_query(F.data.startswith("doc_c:"))
async def docs_country(cb: CallbackQuery, state: FSMContext):
    await state.update_data(doc_c=cb.data.split(":")[1])
    items = [(n, f"doc_s:{k}") for k, n in SENDER.items()]
    await show(cb, "Тип отправителя:", choice_kb(items, back="docs", width=2))


@router.callback_query(F.data.startswith("doc_s:"))
async def docs_sender(cb: CallbackQuery, state: FSMContext):
    await state.update_data(doc_s=cb.data.split(":")[1])
    items = [(n, f"doc_t:{k}") for k, n in KIND.items()]
    await show(cb, "Тип отправления:", choice_kb(items, back="docs", width=2))


@router.callback_query(F.data.startswith("doc_t:"))
async def docs_kind(cb: CallbackQuery, state: FSMContext):
    await state.update_data(doc_t=cb.data.split(":")[1], done=[])
    await _render_checklist(cb, state)


async def _render_checklist(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    if not {"doc_c", "doc_s", "doc_t"} <= d.keys():
        return await show(cb, "Сессия устарела. Начните заново.", choice_kb([("Начать", "docs")]))
    items = build_checklist(d["doc_c"], d["doc_s"], d["doc_t"])
    done = {i for i in d.get("done", []) if i < len(items)}
    await show(cb, checklist_text(items, done, d["doc_c"], d["doc_s"], d["doc_t"]), checklist_kb(items, done))


@router.callback_query(F.data.startswith("doc_x:"))
async def docs_toggle(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    done = set(d.get("done", []))
    i = int(cb.data.split(":")[1])
    done.symmetric_difference_update({i})
    await state.update_data(done=sorted(done))
    await _render_checklist(cb, state)


@router.callback_query(F.data == "doc_reset")
async def docs_reset(cb: CallbackQuery, state: FSMContext):
    await state.update_data(done=[])
    await _render_checklist(cb, state)


# ---------------------------------------------------------------------------
# 5. Техническая поддержка
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "support")
async def support_start(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    items = [(c["name"], f"sup:{k}") for k, c in CARRIERS.items()]
    await show(
        cb,
        "<b>Техническая поддержка</b>\nВопросы по заказу, тарифам, статусу груза и претензиям решает "
        "служба поддержки самой транспортной компании. Выберите перевозчика:",
        choice_kb(items),
    )


@router.callback_query(F.data.startswith("sup:"))
async def support_carrier(cb: CallbackQuery):
    c = CARRIERS[cb.data.split(":")[1]]
    urls = [(f"Поддержка {c['name']}", c["support"])]
    if c["faq"]:
        urls.append(("Вопросы и ответы / сайт", c["faq"]))
    await show(
        cb,
        f"<b>{c['name']}</b>\n{c['about']}\n\n"
        "<i>Телефоны мы не копируем: контакты меняются, актуальные номера и чаты — на официальных страницах.</i>",
        choice_kb([], back="support", extra_urls=urls),
    )


# ---------------------------------------------------------------------------
# Всё остальное
# ---------------------------------------------------------------------------


@router.message()
async def fallback(message: Message):
    await message.answer("Я вас не понял. Выберите раздел в меню:", reply_markup=menu_kb())


async def main():
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Не задан BOT_TOKEN. Укажите токен в переменной окружения или в файле .env")

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    me = await bot.get_me()
    logging.info("Бот запущен: @%s", me.username)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
