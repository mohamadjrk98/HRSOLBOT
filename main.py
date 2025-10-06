import os
import logging
from typing import Dict, Any, Optional
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ---------------- Logging ----------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- Environment Variables ----------------
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID_ENV = os.getenv('ADMIN_CHAT_ID')
HR_CONTACT_INFO = os.getenv('HR_CONTACT_INFO', 'مسؤول الموارد البشرية')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')  # الرابط الكامل للـWebhook (مثال: https://yourapp.onrender.com/)

ADMIN_CHAT_ID: Optional[int] = None
if ADMIN_CHAT_ID_ENV:
    try:
        ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_ENV)
    except ValueError:
        logger.error("ADMIN_CHAT_ID يجب أن يكون رقماً صحيحاً. تم تجاهل القيمة الحالية.")

# ---------------- States ----------------
(
    MAIN_MENU, FULL_NAME, TEAM_NAME,
    APOLOGY_TYPE, APOLOGY_REASON, APOLOGY_NOTES, APOLOGY_CONFIRM,
    LEAVE_START_DATE, LEAVE_END_DATE, LEAVE_REASON, LEAVE_NOTES, LEAVE_CONFIRM,
    INITIATIVE_NAME, INITIATIVE_DETAILS, INITIATIVE_CONFIRM,
    PROBLEM_DETAILS, PROBLEM_NOTES, PROBLEM_CONFIRM,
) = range(18)

TEAM_NAMES = ["فريق الإعلام", "فريق التنسيق", "فريق الدعم اللوجستي", "إدارة المشروع"]

# ---------------- Keyboards ----------------
def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        ["اعتذار عن مهمة", "إجازة/انقطاع"],
        ["تقديم مقترح/مبادرة", "ملاحظة/شكوى"],
        ["معلومات الاتصال بالموارد البشرية"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def get_team_selection_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[team] for team in TEAM_NAMES]
    keyboard.append(["إلغاء ❌"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_confirmation_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [["تأكيد وإرسال ✅"], ["إلغاء ❌"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

# ---------------- إرسال للإدارة ----------------
async def send_to_admin(context: ContextTypes.DEFAULT_TYPE, title: str, fields: Dict[str, Any]):
    if ADMIN_CHAT_ID is None:
        logger.error("ADMIN_CHAT_ID غير مُعرّف، لا يمكن إرسال الرسالة.")
        return

    message_parts = [f"<b>📢 طلب جديد: {title}</b>\n"]
    user_id = context.user_data.get('user_id', 'غير متوفر')
    user_name = context.user_data.get('full_name', 'مستخدم غير مسجل')
    message_parts.append(f"👤 مرسل الطلب: {user_name} (<code>{user_id}</code>)\n")

    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str) and len(value) > 100:
            message_parts.append(f"• <b>{key}:</b>\n<pre>{value}</pre>")
        else:
            message_parts.append(f"• <b>{key}:</b> <i>{value}</i>")

    message = "\n".join(message_parts)
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=message,
            parse_mode='HTML'
        )
        logger.info(f"تم إرسال '{title}' من {user_id} إلى الأدمن ({ADMIN_CHAT_ID}).")
    except Exception as e:
        logger.error(f"فشل إرسال رسالة إلى الأدمن {ADMIN_CHAT_ID}: {e}")

# ---------------- Handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    context.user_data.clear()
    context.user_data['user_id'] = user.id
    await update.message.reply_text(
        f"أهلاً بك يا {user.first_name} في نظام الموارد البشرية لفريق أبناء الأرض. كيف يمكنني خدمتك؟",
        reply_markup=get_main_menu_keyboard()
    )
    return MAIN_MENU

# هنا ضع جميع Handlers الأخرى: main_menu، handle_full_name، handle_team_name، handle_apology_*, handle_leave_*, handle_initiative_*, handle_problem_*, confirm_and_send، fallback_to_main_menu، help_command
# (يمكن نسخهم مباشرة من نسخة Polling السابقة التي أرسلتها لك)

# ---------------- Initialize Application ----------------
application: Optional[Application] = None

def initialize_application():
    global application
    if not BOT_TOKEN or not WEBHOOK_URL:
        logger.error("🚫 BOT_TOKEN أو WEBHOOK_URL غير معرف. لا يمكن بدء البوت.")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # إضافة ConversationHandler هنا (انسخ كامل Handler السابق)
    # مثال: app.add_handler(conv_handler)
    # إضافة أمر /help
    # app.add_handler(CommandHandler("help", help_command))

    # ضبط أوامر البوت
    async def set_commands(_app):
        await _app.bot.set_my_commands([
            BotCommand("start", "بدء المحادثة"),
            BotCommand("help", "عرض المساعدة")
        ])
    app.post_init = set_commands

    # إعداد Webhook
    app.start_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        webhook_url=WEBHOOK_URL
    )

    application = app
    logger.info("تمت تهيئة تطبيق البوت مع Webhook بنجاح.")

# ---------------- WSGI Entry Point ----------------
def wsgi_app(environ, start_response):
    global application
    try:
        if application is None:
            initialize_application()
        start_response('200 OK', [('Content-Type', 'text/plain')])
        return [b'Bot is running']
    except Exception as e:
        import traceback
        start_response('500 INTERNAL SERVER ERROR', [('Content-Type', 'text/plain')])
        return [traceback.format_exc().encode('utf-8')]
