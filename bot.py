# -*- coding: utf-8 -*-

import requests
import json
import os
import time
import jdatetime
import pytz
from datetime import datetime
from dotenv import load_dotenv
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.error import BadRequest
from telegram.constants import ParseMode

# --- بخش ۱: بارگذاری تنظیمات و متغیرهای اصلی ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BRSAPI_KEY = os.getenv("BRSAPI_KEY")

if not TELEGRAM_TOKEN or not BRSAPI_KEY:
    raise ValueError(
        "خطای حیاتی: متغیرهای TELEGRAM_TOKEN یا BRSAPI_KEY در فایل .env یافت نشدند."
    )

HOURLY_DATA_FILE = "hourly_prices.json"
USER_SETTINGS_FILE = "user_settings.json"

FULL_SYMBOL_LIST = {
    "gold": {
        "IR_COIN_EMAMI": {"name": "سکه امامی", "emoji": "🌕"},
        "IR_COIN_BAHAR": {"name": "سکه بهار", "emoji": "🌕"},
        "IR_COIN_HALF": {"name": "نیم سکه", "emoji": "🌕"},
        "IR_COIN_QUARTER": {"name": "ربع سکه", "emoji": "🌕"},
        "IR_COIN_1G": {"name": "سکه گرمی", "emoji": "🌕"},
        "IR_GOLD_18K": {"name": "گرم طلا", "emoji": "💫"},
        "IR_GOLD_MELTED": {"name": "طلای آب‌شده", "emoji": "🔥"},
        "IR_GOLD_MESGHAL": {"name": "مثقال طلا", "emoji": "💫"},
        "XAUUSD": {"name": "انس طلا", "emoji": "💰"},
    },
    "currency": {
        "USD": {"name": "دلار", "emoji": "🇺🇸"},
        "EUR": {"name": "یورو", "emoji": "🇪🇺"},
        "AED": {"name": "درهم امارات", "emoji": "🇦🇪"},
        "GBP": {"name": "پوند انگلیس", "emoji": "🇬🇧"},
        "TRY": {"name": "لیر ترکیه", "emoji": "🇹🇷"},
        "USDT_IRT": {"name": "دلار تتر", "emoji": "💲"},
        "JPY": {"name": "ین ژاپن", "emoji": "🇯🇵"},
        "CHF": {"name": "فرانک سوئیس", "emoji": "🇨🇭"},
        "AUD": {"name": "دلار استرالیا", "emoji": "🇦🇺"},
        "CAD": {"name": "دلار کانادا", "emoji": "🇨🇦"},
        "CNY": {"name": "یوان چین", "emoji": "🇨🇳"},
    },
    "crypto": {
        "BTC": {"name": "بیت‌کوین", "emoji": "🟠"},
        "ETH": {"name": "اتریوم", "emoji": "💎"},
        "BNB": {"name": "بایننس کوین", "emoji": "🔶"},
        "SOL": {"name": "سولانا", "emoji": "🟣"},
        "XRP": {"name": "ریپل", "emoji": "🔵"},
        "DOGE": {"name": "دوج‌کوین", "emoji": "🐕"},
        "ADA": {"name": "کاردانو", "emoji": "🧊"},
        "SHIB": {"name": "شیبا اینو", "emoji": "🦊"},
    },
}
REPORT_TYPES = {
    "currency": "💵 نرخ ارزها",
    "gold": "🪙 نرخ طلا و سکه",
    "crypto": "📈 ارزهای دیجیتال",
    "bubble": "🫧 تحلیل حباب",
}


# --- بخش ۲: توابع مدیریت داده و API ---
async def update_hourly_data(context: ContextTypes.DEFAULT_TYPE):
    print(f"Running hourly job at {time.strftime('%Y-%m-%d %H:%M:%S')}...")
    prices = get_and_process_prices(BRSAPI_KEY)
    if prices:
        with open(HOURLY_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"timestamp": time.time(), "prices": prices},
                f,
                ensure_ascii=False,
                indent=4,
            )
        print("Hourly data successfully updated.")
    else:
        print("Failed to update hourly data: API call failed.")


def read_hourly_prices():
    if not os.path.exists(HOURLY_DATA_FILE):
        return {}
    try:
        with open(HOURLY_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("prices", {})
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def load_user_settings():
    if not os.path.exists(USER_SETTINGS_FILE):
        return {}
    try:
        with open(USER_SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_user_settings(all_settings):
    with open(USER_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_settings, f, indent=4, ensure_ascii=False)


def get_user_prefs(user_id):
    all_settings = load_user_settings()
    user_id_str = str(user_id)

    # اگر کاربر جدید است، پروفایل کامل بساز
    if user_id_str not in all_settings:
        all_settings[user_id_str] = {
            "currency": ["USD", "EUR", "AED", "USDT_IRT"],
            "gold": ["IR_COIN_EMAMI", "IR_GOLD_18K"],
            "crypto": ["BTC", "ETH"],
            "schedule": {
                "active": False,
                "times": ["09:00"],
                "reports": ["gold", "bubble"],
            },
        }
        save_user_settings(all_settings)
        return all_settings[user_id_str]

    # اگر کاربر قدیمی است، پروفایل او را برای سازگاری با نسخه جدید بروزرسانی کن
    user_prefs = all_settings[user_id_str]
    made_changes = False
    if "schedule" not in user_prefs or "times" not in user_prefs.get("schedule", {}):
        user_prefs["schedule"] = {
            "active": False,
            "times": ["09:00"],
            "reports": ["gold", "bubble"],
        }
        made_changes = True
    for cat in FULL_SYMBOL_LIST:
        if cat not in user_prefs:
            user_prefs[cat] = []
            made_changes = True

    if made_changes:
        save_user_settings(all_settings)

    return user_prefs


def get_and_process_prices(api_key):
    url = "https://BrsApi.ir/Api/Market/Gold_Currency.php"
    params = {"key": api_key}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MyGoldBot/4.3)"}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        raw_data = response.json()
        processed_prices = {}
        for category in ["gold", "currency", "cryptocurrency"]:
            for item in raw_data.get(category, []):
                processed_prices[item["symbol"]] = item
        if "IR_GOLD_18K" in processed_prices:
            geram_price = float(processed_prices["IR_GOLD_18K"]["price"])
            processed_prices["IR_GOLD_MESGHAL"] = {"price": geram_price * 4.6083}
        return processed_prices
    except Exception as e:
        print(f"Error in get_and_process_prices: {e}")
        return None


def format_change(current_price, hourly_price):
    if not hourly_price or hourly_price == 0:
        return ""
    change = current_price - hourly_price
    percent_change = (change / hourly_price) * 100
    emoji = "➖" if -0.1 < percent_change < 0.1 else "▲" if percent_change > 0 else "▼"
    return f" ({emoji} {percent_change:+.2f}%)"


def calculate_all_bubbles(prices):
    bubbles = {}
    try:
        ounce_price, dollar_price = float(prices["XAUUSD"]["price"]), float(
            prices["USD"]["price"]
        )
        gram_price_global = (ounce_price * dollar_price) / 31.1035
        items_to_calc = {
            "IR_COIN_EMAMI": (8.133, 300000),
            "IR_COIN_BAHAR": (8.133, 300000),
            "IR_COIN_HALF": (4.0665, 150000),
            "IR_COIN_QUARTER": (2.03325, 100000),
        }
        for symbol, (weight, mint_cost) in items_to_calc.items():
            if symbol in prices:
                market, intrinsic = (
                    float(prices[symbol]["price"]),
                    (gram_price_global * weight * 0.900) + mint_cost,
                )
                bubbles[symbol] = {
                    "market": market,
                    "intrinsic": intrinsic,
                    "percent": ((market - intrinsic) / intrinsic) * 100,
                }
        if "IR_GOLD_18K" in prices:
            market, intrinsic = (
                float(prices["IR_GOLD_18K"]["price"]),
                gram_price_global * 0.75,
            )
            bubbles["IR_GOLD_18K"] = {
                "market": market,
                "intrinsic": intrinsic,
                "percent": ((market - intrinsic) / intrinsic) * 100,
            }
        if "IR_GOLD_MESGHAL" in prices:
            market, intrinsic = (
                float(prices["IR_GOLD_MESGHAL"]["price"]),
                (gram_price_global * 0.75) * 4.6083,
            )
            bubbles["IR_GOLD_MESGHAL"] = {
                "market": market,
                "intrinsic": intrinsic,
                "percent": ((market - intrinsic) / intrinsic) * 100,
            }
        return bubbles
    except KeyError as e:
        print(f"Base data for bubble calc missing: {e}")
        return None


def get_persian_date_header():
    tehran_zone = pytz.timezone("Asia/Tehran")
    tehran_dt = datetime.now(tehran_zone)
    jdate = jdatetime.datetime.fromgregorian(datetime=tehran_dt)
    persian_days, persian_months = [
        "شنبه",
        "یکشنبه",
        "دوشنبه",
        "سه‌شنبه",
        "چهارشنبه",
        "پنجشنبه",
        "جمعه",
    ], [
        "فروردین",
        "اردیبهشت",
        "خرداد",
        "تیر",
        "مرداد",
        "شهریور",
        "مهر",
        "آبان",
        "آذر",
        "دی",
        "بهمن",
        "اسفند",
    ]
    return f"📆 {persian_days[jdate.weekday()]} {jdate.day} {persian_months[jdate.month-1]}    🕰 {jdate.strftime('%H:%M')}"


# --- بخش ۳: توابع اصلی ربات ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [KeyboardButton("💵 نرخ ارزها"), KeyboardButton("🪙 نرخ طلا و سکه")],
        [KeyboardButton("📈 ارزهای دیجیتال"), KeyboardButton("🫧 تحلیل حباب")],
        [KeyboardButton("⚙️ تنظیمات")],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_html(
        "سلام! به ربات تحلیل‌گر شخصی شما خوش آمدید.", reply_markup=reply_markup
    )


async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_message = update.message.text
    if user_message == "⚙️ تنظیمات":
        await show_settings_main_menu(update)
        return
    await update.message.reply_text("در حال دریافت قیمت‌های لحظه‌ای و مقایسه...")
    live_prices = get_and_process_prices(BRSAPI_KEY)
    if not live_prices:
        await update.message.reply_text(
            "❌ <b>خطای دریافت قیمت لحظه‌ای</b>. سرور API پاسخگو نیست.",
            parse_mode=ParseMode.HTML,
        )
        return
    date_header = get_persian_date_header()
    message_text = "لطفاً از دکمه‌های منو استفاده کنید."
    if user_message == "🫧 تحلیل حباب":
        message_text = build_bubble_report(live_prices)
    elif user_message in ["💵 نرخ ارزها", "🪙 نرخ طلا و سکه", "📈 ارزهای دیجیتال"]:
        user_prefs = get_user_prefs(update.effective_user.id)
        category = (
            "currency"
            if user_message == "💵 نرخ ارزها"
            else "gold" if user_message == "🪙 نرخ طلا و سکه" else "crypto"
        )
        message_text = build_single_report(
            category, user_prefs, live_prices, read_hourly_prices()
        )
    await update.message.reply_text(
        text=f"{date_header}\n\n{message_text}", parse_mode=ParseMode.HTML
    )


# --- توابع ساخت گزارش ---
def build_single_report(category, user_prefs, live_prices, hourly_prices):
    title_emoji = (
        "💵" if category == "currency" else "🪙" if category == "gold" else "📈"
    )
    title = f"{title_emoji} <b>نرخ لحظه‌ای {category.title()}</b>\n\n"
    report_text, found_items = title, 0
    for symbol in user_prefs.get(category, []):
        if symbol in live_prices:
            found_items += 1
            price, hourly_price = float(live_prices[symbol]["price"]), float(
                hourly_prices.get(symbol, {}).get("price", 0)
            )
            symbol_info = FULL_SYMBOL_LIST.get(category, {}).get(symbol, {})
            emoji, display_name = symbol_info.get("emoji", "▫️"), symbol_info.get(
                "name", symbol
            )
            if category == "crypto":
                price_format = ",.8f" if price < 0.01 else ",.2f"
                report_text += f"{emoji} <b>{display_name}</b> ({symbol})\n<code>${price:{price_format}}</code>{format_change(price, hourly_price)}\n\n"
            else:
                report_text += f"{emoji} <b>{display_name}:</b> <code>{int(price):,} تومان</code>{format_change(price, hourly_price)}\n"
    if found_items == 0:
        return "موردی برای نمایش انتخاب نشده است. لطفاً از منوی «تنظیمات»، آیتم‌های دلخواه خود را برای این بخش فعال کنید."
    return report_text


def build_bubble_report(live_prices):
    all_bubbles = calculate_all_bubbles(live_prices)
    if not all_bubbles:
        return "❌ <b>خطا در تحلیل:</b> داده‌های ضروری برای محاسبه دریافت نشد."
    market_prices_text = "\n\n🪙 <b>قیمت لحظه‌ای بازار</b>\n#قیمت_بازار\n"
    display_order = [
        "IR_COIN_EMAMI",
        "IR_COIN_BAHAR",
        "IR_COIN_HALF",
        "IR_COIN_QUARTER",
        "IR_GOLD_MESGHAL",
        "IR_GOLD_18K",
        "XAUUSD",
    ]
    for symbol in display_order:
        if symbol in live_prices:
            info, emoji, name = FULL_SYMBOL_LIST["gold"].get(symbol, {}), "▫️", symbol
            if info:
                emoji, name = info.get("emoji", "▫️"), info.get("name", symbol)
            price = float(live_prices[symbol]["price"])
            if symbol == "XAUUSD":
                market_prices_text += (
                    f"{emoji} <b>{name}:</b> <code>{price:,.2f}$</code>\n"
                )
            else:
                market_prices_text += (
                    f"{emoji} <b>{name}:</b> <code>{int(price):,} تومان</code>\n"
                )
    intrinsic_prices_text = f"\n\n💎 <b>ارزش ذاتی و درصد حباب</b>\n با احتساب دلار <code>{int(live_prices['USD']['price']):,}</code> تومان\n"
    for symbol in display_order:
        if symbol in all_bubbles and symbol != "XAUUSD":
            info, emoji, name = FULL_SYMBOL_LIST["gold"].get(symbol, {}), "▫️", symbol
            if info:
                emoji, name = info.get("emoji", "▫️"), info.get("name", symbol)
            data = all_bubbles[symbol]
            intrinsic_prices_text += f"{emoji} <b>{name}:</b> <code>{int(data['intrinsic']):,}</code> - ({data['percent']:+.2f}%)\n"
    coin_bubble_percent = all_bubbles["IR_COIN_EMAMI"]["percent"]
    if coin_bubble_percent < 3:
        strategy_text = "حباب سکه در <b>محدوده پایین (منطقه خرید)</b> قرار دارد. جذابیت <b>خرید سکه</b> یا تبدیل طلای آب‌شده به سکه، افزایش می‌یابد."
    elif 3 <= coin_bubble_percent <= 7:
        strategy_text = "حباب سکه در <b>محدوده تعادل</b> است. استراتژی منطقی در این بازه، <b>نگهداری دارایی فعلی</b> (چه سکه و چه طلای آب‌شده) به نظر می‌رسد."
    elif 7 < coin_bubble_percent <= 15:
        strategy_text = "حباب سکه در <b>محدوده بالا (منطقه احتیاط)</b> قرار دارد. این شرایط، فرصت <b>فروش پله‌ای سکه</b> و تبدیل آن به طلای آب‌شده را فراهم می‌کند."
    else:
        strategy_text = "حباب سکه در <b>محدوده بسیار بالا (منطقه ریسک)</b> است. ریسک کاهش حباب قابل توجه است و <b>تبدیل سکه به طلای آب‌شده</b> گزینه‌ای کم‌ریسک‌تر به نظر می‌رسد."
    analysis_text = f"\n----------------------------------------\n💡 <b>تحلیل استراتژیک (بر اساس حباب سکه امامی):</b>\n{strategy_text}\n\n⚠️ <b>سلب مسئولیت:</b>\n<i>این تحلیل یک پیشنهاد مالی یا سرمایه‌گذاری نیست و صرفاً بر اساس داده‌های لحظه‌ای و فرمول‌های ریاضی ارائه شده است. مسئولیت هرگونه معامله بر عهده کاربر می‌باشد.</i>"
    return market_prices_text + intrinsic_prices_text + analysis_text


# --- توابع مدیریت منوها ---
async def show_settings_main_menu(update_or_query):
    keyboard = [
        [InlineKeyboardButton("💵 تنظیمات ارزها", callback_data="settings_currency")],
        [InlineKeyboardButton("🪙 تنظیمات طلا و سکه", callback_data="settings_gold")],
        [InlineKeyboardButton("📈 تنظیمات رمزارزها", callback_data="settings_crypto")],
        [
            InlineKeyboardButton(
                "⏰ زمان‌بندی پیام خودکار", callback_data="settings_schedule"
            )
        ],
        [InlineKeyboardButton("❌ بستن", callback_data="close_settings")],
    ]
    message_text = "منوی تنظیمات:"
    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(
            message_text, reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update_or_query.edit_message_text(
            message_text, reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def show_item_selection_menu(query, callback_data):
    category = callback_data.split("_")[1]
    user_prefs = get_user_prefs(query.from_user.id)
    keyboard, row = [], []
    for symbol, info in FULL_SYMBOL_LIST.get(category, {}).items():
        is_selected = symbol in user_prefs.get(category, [])
        icon = "✅" if is_selected else "🔲"
        button_text = f"{icon} {info['emoji']} {info['name']}"
        button_callback = f"toggle_{category}_{symbol}"
        row.append(InlineKeyboardButton(button_text, callback_data=button_callback))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append(
        [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="settings_main")]
    )
    try:
        await query.edit_message_text(
            f"موارد مورد نظر برای نمایش در بخش <b>{category.replace('_', ' ').title()}</b> را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
        )
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise


async def toggle_display_item(query, callback_data):
    _, category, symbol = callback_data.split("_", 2)
    user_id = query.from_user.id
    get_user_prefs(user_id)  # اطمینان از وجود پروفایل و سازگاری آن
    all_settings = load_user_settings()
    pref_list = all_settings[str(user_id)].get(category, [])
    if symbol in pref_list:
        pref_list.remove(symbol)
    else:
        pref_list.append(symbol)
    save_user_settings(all_settings)
    await show_item_selection_menu(query, f"settings_{category}")


async def show_schedule_menu(query):
    user_prefs = get_user_prefs(query.from_user.id)
    schedule_info = user_prefs.get("schedule", {})
    status, schedule_times = (
        "✅ فعال" if schedule_info.get("active") else "❌ غیرفعال"
    ), schedule_info.get("times", [])
    times_str = (
        ", ".join(sorted(schedule_times))
        if schedule_times
        else "<i>هیچ ساعتی انتخاب نشده</i>"
    )
    text = f"<b>تنظیمات پیام خودکار:</b>\nوضعیت فعلی: <b>{status}</b>\nساعت‌های ارسال: {times_str}\n\nگزارش‌های زیر در ساعات مقرر ارسال خواهند شد:"
    keyboard, row = [], []
    for report_key, report_name in REPORT_TYPES.items():
        is_selected = report_key in schedule_info.get("reports", [])
        icon = "✅" if is_selected else "🔲"
        row.append(
            InlineKeyboardButton(
                f"{icon} {report_name}",
                callback_data=f"schedule_toggle_report_{report_key}",
            )
        )
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append(
        [InlineKeyboardButton("🕰 تنظیم ساعات", callback_data="schedule_set_time")]
    )
    keyboard.append(
        [
            InlineKeyboardButton(
                f"{'غیرفعال کردن' if status == '✅ فعال' else 'فعال کردن'} زمان‌بندی",
                callback_data="schedule_toggle_active",
            )
        ]
    )
    keyboard.append(
        [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="settings_main")]
    )
    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML
    )


async def show_time_selection_menu(query):
    user_prefs = get_user_prefs(query.from_user.id)
    selected_times = user_prefs.get("schedule", {}).get("times", [])
    keyboard = []
    for i in range(0, 24, 4):
        row = []
        for j in range(4):
            hour = i + j
            time_str = f"{hour:02d}:00"
            icon = "✅" if time_str in selected_times else "🔲"
            row.append(
                InlineKeyboardButton(
                    f"{icon} {time_str}",
                    callback_data=f"schedule_toggle_time_{time_str}",
                )
            )
        keyboard.append(row)
    keyboard.append(
        [
            InlineKeyboardButton(
                "🔙 بازگشت به زمان‌بندی", callback_data="settings_schedule"
            )
        ]
    )
    await query.edit_message_text(
        "ساعات مورد نظر برای ارسال گزارش را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def toggle_schedule_time(query, callback_data):
    time_str = callback_data.split("_")[-1]
    user_id = query.from_user.id
    get_user_prefs(user_id)  # اطمینان از وجود پروفایل
    all_settings = load_user_settings()
    time_list = all_settings[str(user_id)]["schedule"]["times"]
    if time_str in time_list:
        time_list.remove(time_str)
    else:
        time_list.append(time_str)
    save_user_settings(all_settings)
    await show_time_selection_menu(query)


async def toggle_schedule_report(query, callback_data):
    report_key = callback_data.split("_")[-1]
    user_id = query.from_user.id
    get_user_prefs(user_id)
    all_settings = load_user_settings()
    report_list = all_settings[str(user_id)]["schedule"]["reports"]
    if report_key in report_list:
        report_list.remove(report_key)
    else:
        report_list.append(report_key)
    save_user_settings(all_settings)
    await show_schedule_menu(query)


async def toggle_schedule_active(query):
    user_id = query.from_user.id
    get_user_prefs(user_id)
    all_settings = load_user_settings()
    all_settings[str(user_id)]["schedule"]["active"] = not all_settings[str(user_id)][
        "schedule"
    ].get("active", False)
    save_user_settings(all_settings)
    await show_schedule_menu(query)


async def settings_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    callback_data = query.data
    if callback_data == "close_settings":
        await query.message.delete()
    elif callback_data == "settings_main":
        await show_settings_main_menu(query)
    elif callback_data == "settings_schedule":
        await show_schedule_menu(query)
    elif callback_data == "schedule_set_time":
        await show_time_selection_menu(query)
    elif callback_data.startswith("schedule_toggle_time_"):
        await toggle_schedule_time(query, callback_data)
    elif callback_data.startswith("schedule_toggle_report_"):
        await toggle_schedule_report(query, callback_data)
    elif callback_data == "schedule_toggle_active":
        await toggle_schedule_active(query)
    elif callback_data.startswith("toggle_"):
        await toggle_display_item(query, callback_data)
    elif callback_data.startswith("settings_"):
        await show_item_selection_menu(query, callback_data)


async def send_aggregated_report(chat_id, report_types, context, live_prices=None):
    if not live_prices:
        live_prices = get_and_process_prices(BRSAPI_KEY)
    if not live_prices:
        return
    user_prefs, hourly_prices = get_user_prefs(chat_id), read_hourly_prices()
    final_report = f"🔔 <b>گزارش خودکار شما - {get_persian_date_header()}</b>\n"
    final_report += "====================\n"
    # مرتب کردن گزارش‌ها برای نمایش بهتر
    for report_type in sorted(
        report_types, key=lambda x: list(REPORT_TYPES.keys()).index(x)
    ):
        if report_type == "bubble":
            final_report += build_bubble_report(live_prices) + "\n\n"
        else:
            final_report += (
                build_single_report(report_type, user_prefs, live_prices, hourly_prices)
                + "\n"
            )
    await context.bot.send_message(
        chat_id=chat_id, text=final_report, parse_mode=ParseMode.HTML
    )


async def auto_message_scheduler(context: ContextTypes.DEFAULT_TYPE):
    current_time = datetime.now(pytz.timezone("Asia/Tehran")).strftime("%H:%M")
    all_settings = load_user_settings()
    for user_id, prefs in all_settings.items():
        schedule_info = prefs.get("schedule", {})
        if schedule_info.get("active") and current_time in schedule_info.get(
            "times", []
        ):
            report_types = schedule_info.get("reports", [])
            if report_types:
                print(f"Sending scheduled report to {user_id} at {current_time}")
                try:
                    await send_aggregated_report(user_id, report_types, context)
                except Exception as e:
                    print(f"Failed to send scheduled message to {user_id}: {e}")


def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    job_queue = application.job_queue
    job_queue.run_repeating(update_hourly_data, interval=3600, first=5)
    job_queue.run_repeating(auto_message_scheduler, interval=60)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)
    )
    application.add_handler(CallbackQueryHandler(settings_callback_handler))
    print("✅ ربات نهایی با زمان‌بندی چندگانه و معماری کامل اجرا شد...")
    application.run_polling()


if __name__ == "__main__":
    main()
