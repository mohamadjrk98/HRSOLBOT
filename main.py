# main.py
import os
import logging
from typing import Final, Dict, Any, Optional
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# --------------------------------- إعداد التسجيل (Logging) ---------------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --------------------------------- متغيرات البيئة (Environment Variables) ---------------------------------
BOT_TOKEN: Final[Optional[str]] = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID_ENV: Final[Optional[str]] = os.getenv('ADMIN_CHAT_ID')
HR_CONTACT_INFO: Final[str] = os.getenv('HR_CONTACT_INFO', 'مسؤول الموارد البشرية (يرجى تحديد جهة الاتصال)')
WEBHOOK_URL: Final[Optional[str]] = os.getenv('WEBHOOK_URL')
PORT: Final[int] = int(os.getenv('PORT', 8080))

# تأكد من تحويل ADMIN_CHAT_ID إلى int عندما يكون مُعرّفاً
ADMIN_CHAT_ID: Optional[int] = None
if ADMIN_CHAT_ID_ENV:
    try:
        ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_ENV)
    except ValueError:
        logger.error("ADMIN_CHAT_ID يجب أن يكون رقماً صحيحاً. تم تجاهل ADMIN_CHAT_ID الحالي.")

# --------------------------------- تعريف الحالات (States) ---------------------------------
(
    MAIN_MENU, FULL_NAME, TEAM_NAME,
    APOLOGY_TYPE, APOLOGY_REASON, APOLOGY_NOTES, APOLOGY_CONFIRM,
    LEAVE_START_DATE, LEAVE_END_DATE, LEAVE_REASON, LEAVE_NOTES, LEAVE_CONFIRM,
    INITIATIVE_NAME, INITIATIVE_DETAILS, INITIATIVE_CONFIRM,
    PROBLEM_DETAILS, PROBLEM_NOTES, PROBLEM_CONFIRM,
) = range(18)
# قائمة فرق العمل
TEAM_NAMES: Final[list[str]] = ["فريق الإعلام", "فريق التنسيق", "فريق الدعم اللوجستي", "إدارة المشروع"]

# --------------------------------- دوال لوحة المفاتيح ---------------------------------
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

# --------------------------------- إرسال للإدارة ---------------------------------
async def send_to_admin(context: ContextTypes.DEFAULT_TYPE, title: str, fields: Dict[str, Any]) -> None:
    """تجميع البيانات وإرسالها إلى مسؤول الموارد البشرية."""
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

# --------------------------------- معالجات المحادثة ---------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    context.user_data.clear()
    context.user_data['user_id'] = user.id
    await update.message.reply_text(
        f"أهلاً بك يا {user.first_name} في نظام الموارد البشرية لفريق أبناء الأرض. كيف يمكنني خدمتك؟",
        reply_markup=get_main_menu_keyboard()
    )
    return MAIN_MENU

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """استقبال نص من المستخدم وتوجيهه بناءً على الخيارات."""
    text = (update.message.text or "").strip()
    # لا نمسح user_data هنا لنحتفظ بالبيانات أثناء خطوات متعددة
    context.user_data.setdefault('user_id', update.effective_user.id)

    if "اعتذار" in text:
        context.user_data['next_step'] = APOLOGY_TYPE
        action_name = "طلب اعتذار"
    elif "إجازة" in text:
        context.user_data['next_step'] = LEAVE_START_DATE
        action_name = "طلب إجازة"
    elif "مقترح" in text or "مبادرة" in text:
        context.user_data['next_step'] = INITIATIVE_NAME
        action_name = "تقديم مقترح"
    elif "ملاحظة" in text or "شكوى" in text:
        context.user_data['next_step'] = PROBLEM_DETAILS
        action_name = "تقديم شكوى/ملاحظة"
    elif "معلومات الاتصال" in text:
        await update.message.reply_text(
            f"يمكنك التواصل مع:\n\n{HR_CONTACT_INFO}",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU
    else:
        await update.message.reply_text("يرجى اختيار أحد الأزرار من القائمة.", reply_markup=get_main_menu_keyboard())
        return MAIN_MENU

    # نبدأ العملية بطلب الاسم الكامل
    await update.message.reply_text(f"لبدء {action_name}، أرسل اسمك الكامل:", reply_markup=ReplyKeyboardRemove())
    return FULL_NAME

async def handle_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    full_name = (update.message.text or "").strip()
    # تحقق بسيط من صحة الاسم
    if len(full_name) < 3:
        await update.message.reply_text("يرجى إدخال اسم كامل مكوّن من 3 أحرف على الأقل.")
        return FULL_NAME

    context.user_data['full_name'] = full_name

    await update.message.reply_text(
        "شكراً. الآن اختر فريقك:",
        reply_markup=get_team_selection_keyboard()
    )
    return TEAM_NAME

async def handle_team_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    team_name = (update.message.text or "").strip()
    if team_name == "إلغاء ❌":
        return await fallback_to_main_menu(update, context)

    if team_name not in TEAM_NAMES:
        await update.message.reply_text("يرجى اختيار فريق من القائمة أو إلغاء.", reply_markup=get_team_selection_keyboard())
        return TEAM_NAME

    context.user_data['team_name'] = team_name
    next_step = context.user_data.pop('next_step', MAIN_MENU)

    # توجيه لخطوات خاصة بكل نوع
    if next_step == APOLOGY_TYPE:
        await update.message.reply_text(
            "ما نوع الاعتذار الذي تود تقديمه؟",
            reply_markup=ReplyKeyboardMarkup([["تأخير عن مهمة", "تأخير عن اجتماع"], ["عدم حضور مهمة", "عدم حضور اجتماع"], ["إلغاء ❌"]], resize_keyboard=True, one_time_keyboard=True)
        )
        return APOLOGY_TYPE

    if next_step == LEAVE_START_DATE:
        await update.message.reply_text("أرسل تاريخ بدء الإجازة (YYYY-MM-DD):", reply_markup=ReplyKeyboardRemove())
        return LEAVE_START_DATE

    if next_step == INITIATIVE_NAME:
        await update.message.reply_text("أدخل اسم المقترح/المبادرة بإيجاز:", reply_markup=ReplyKeyboardRemove())
        return INITIATIVE_NAME

    if next_step == PROBLEM_DETAILS:
        await update.message.reply_text("وصف المشكلة/الشكوى:", reply_markup=ReplyKeyboardRemove())
        return PROBLEM_DETAILS

    return await fallback_to_main_menu(update, context)

# --- اعتذار ---
async def handle_apology_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['apology_type'] = (update.message.text or "").strip()
    await update.message.reply_text("يرجى ذكر سبب الاعتذار بإيجاز:")
    return APOLOGY_REASON

async def handle_apology_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['apology_reason'] = (update.message.text or "").strip()
    await update.message.reply_text("هل لديك ملاحظات إضافية؟ (اكتب 'لا' إذا لا يوجد):")
    return APOLOGY_NOTES

async def handle_apology_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['apology_notes'] = (update.message.text or "").strip()
    data = context.user_data
    summary = (
        f"ملخص طلب الاعتذار:\n"
        f"• الاسم: {data.get('full_name')}\n"
        f"• الفريق: {data.get('team_name')}\n"
        f"• النوع: {data.get('apology_type')}\n"
        f"• السبب: {data.get('apology_reason')}\n"
        f"• ملاحظات: {data.get('apology_notes')}\n\n"
        "هل تريد التأكيد والإرسال؟"
    )
    await update.message.reply_text(summary, reply_markup=get_confirmation_keyboard())
    return APOLOGY_CONFIRM

# --- إجازة/انقطاع ---
async def handle_leave_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['leave_start_date'] = (update.message.text or "").strip()
    await update.message.reply_text("أرسل تاريخ الانتهاء (YYYY-MM-DD):")
    return LEAVE_END_DATE

async def handle_leave_end_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['leave_end_date'] = (update.message.text or "").strip()
    await update.message.reply_text("ما سبب الإجازة؟")
    return LEAVE_REASON

async def handle_leave_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['leave_reason'] = (update.message.text or "").strip()
    await update.message.reply_text("هل لديك ملاحظات أو ترتيبات إضافية؟ (اكتب 'لا' إذا لا يوجد):")
    return LEAVE_NOTES

async def handle_leave_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['leave_notes'] = (update.message.text or "").strip()
    data = context.user_data
    summary = (
        f"ملخص طلب الإجازة:\n"
        f"• الاسم: {data.get('full_name')}\n"
        f"• الفريق: {data.get('team_name')}\n"
        f"• تاريخ البدء: {data.get('leave_start_date')}\n"
        f"• تاريخ الانتهاء: {data.get('leave_end_date')}\n"
        f"• السبب: {data.get('leave_reason')}\n"
        f"• ملاحظات: {data.get('leave_notes')}\n\n"
        "هل تريد التأكيد والإرسال؟"
    )
    await update.message.reply_text(summary, reply_markup=get_confirmation_keyboard())
    return LEAVE_CONFIRM

# --- مبادرة/مقترح ---
async def handle_initiative_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['initiative_name'] = (update.message.text or "").strip()
    await update.message.reply_text("اشرح مقترحك بالتفصيل:")
    return INITIATIVE_DETAILS

async def handle_initiative_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['initiative_details'] = (update.message.text or "").strip()
    data = context.user_data
    summary = (
        f"ملخص المقترح:\n"
        f"• الاسم: {data.get('full_name')}\n"
        f"• الفريق: {data.get('team_name')}\n"
        f"• اسم المقترح: {data.get('initiative_name')}\n"
        f"• التفاصيل:\n{data.get('initiative_details')}\n\n"
        "هل تريد التأكيد والإرسال؟"
    )
    await update.message.reply_text(summary, reply_markup=get_confirmation_keyboard())
    return INITIATIVE_CONFIRM

# --- شكوى/ملاحظة ---
async def handle_problem_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['problem_description'] = (update.message.text or "").strip()
    await update.message.reply_text("هل لديك أدلة أو ملاحظات إضافية؟ (اكتب 'لا' إن لم توجد):")
    return PROBLEM_NOTES

async def handle_problem_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['problem_notes'] = (update.message.text or "").strip()
    data = context.user_data
    summary = (
        f"ملخص الشكوى/الملاحظة:\n"
        f"• الاسم: {data.get('full_name')}\n"
        f"• الفريق: {data.get('team_name')}\n"
        f"• الوصف: {data.get('problem_description')}\n"
        f"• ملاحظات/أدلة: {data.get('problem_notes')}\n\n"
        "هل تريد التأكيد والإرسال؟"
    )
    await update.message.reply_text(summary, reply_markup=get_confirmation_keyboard())
    return PROBLEM_CONFIRM

# --- تأكيد وإرسال مشترك ---
async def confirm_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if text != "تأكيد وإرسال ✅":
        return await fallback_to_main_menu(update, context)

    data = context.user_data
    title = "طلب غير معروف"
    fields: Dict[str, Any] = {}

    if 'apology_type' in data:
        title = "اعتذار عن مهمة"
        fields = {
            "الاسم الكامل": data.get('full_name'),
            "الفريق": data.get('team_name'),
            "نوع الاعتذار": data.get('apology_type'),
            "السبب": data.get('apology_reason'),
            "ملاحظات": data.get('apology_notes'),
        }
    elif 'leave_start_date' in data:
        title = "طلب إجازة/انقطاع"
        fields = {
            "الاسم الكامل": data.get('full_name'),
            "الفريق": data.get('team_name'),
            "تاريخ البدء": data.get('leave_start_date'),
            "تاريخ الانتهاء": data.get('leave_end_date'),
            "السبب": data.get('leave_reason'),
            "ملاحظات": data.get('leave_notes'),
        }
    elif 'initiative_name' in data:
        title = "مقترح/مبادرة"
        fields = {
            "الاسم الكامل": data.get('full_name'),
            "الفريق": data.get('team_name'),
            "اسم المقترح": data.get('initiative_name'),
            "التفاصيل": data.get('initiative_details'),
        }
    elif 'problem_description' in data:
        title = "ملاحظة/شكوى"
        fields = {
            "الاسم الكامل": data.get('full_name'),
            "الفريق": data.get('team_name'),
            "الوصف": data.get('problem_description'),
            "ملاحظات/أدلة": data.get('problem_notes'),
        }

    await send_to_admin(context, title, fields)

    await update.message.reply_text(
        f"✅ تم إرسال طلبك ({title}) بنجاح. سيتم مراجعته من قبل مسؤول الموارد البشرية.",
        reply_markup=get_main_menu_keyboard()
    )

    context.user_data.clear()
    return MAIN_MENU

async def fallback_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "❌ تم إلغاء العملية. عدت إلى القائمة الرئيسية.",
        reply_markup=get_main_menu_keyboard()
    )
    context.user_data.clear()
    return MAIN_MENU

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "نظام الموارد البشرية - أوامر متاحة:\n"
        "• /start - بدء المحادثة.\n"
        "• /help - عرض هذه الرسالة.\n\n"
        "استخدم الأزرار في القائمة للمتابعة."
    )
    await update.message.reply_text(help_text, reply_markup=get_main_menu_keyboard())

# --------------------------------- ضبط أوامر البوت بعد التشغيل ---------------------------------
async def set_bot_commands(app: Application) -> None:
    bot_commands = [
        BotCommand("start", "بدء المحادثة والعودة للقائمة الرئيسية"),
        BotCommand("help", "عرض المساعدة والأوامر المتاحة"),
    ]
    await app.bot.set_my_commands(bot_commands)

# --------------------------------- تهيئة التطبيق ---------------------------------
application: Optional[Application] = None

def initialize_application():
    global application
    if not BOT_TOKEN:
        logger.error("🚫 BOT_TOKEN غير مُعرّف. لا يمكن بدء البوت.")
        return

    try:
        app = Application.builder().token(BOT_TOKEN).build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu)],
                FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_full_name)],
                TEAM_NAME: [MessageHandler(filters.Regex(f"^({'|'.join(TEAM_NAMES)}|إلغاء ❌)$"), handle_team_name),
                            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_team_name)],
                # اعتذار
                APOLOGY_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_apology_type)],
                APOLOGY_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_apology_reason)],
                APOLOGY_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_apology_notes)],
                APOLOGY_CONFIRM: [
                    MessageHandler(filters.Regex("^تأكيد وإرسال ✅$"), confirm_and_send),
                    MessageHandler(filters.Regex("^إلغاء ❌$"), fallback_to_main_menu),
                ],
                # إجازة
                LEAVE_START_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leave_start_date)],
                LEAVE_END_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leave_end_date)],
                LEAVE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leave_reason)],
                LEAVE_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leave_notes)],
                LEAVE_CONFIRM: [
                    MessageHandler(filters.Regex("^تأكيد وإرسال ✅$"), confirm_and_send),
                    MessageHandler(filters.Regex("^إلغاء ❌$"), fallback_to_main_menu),
                ],
                # مبادرة
                INITIATIVE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_initiative_name)],
                INITIATIVE_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_initiative_details)],
                INITIATIVE_CONFIRM: [
                    MessageHandler(filters.Regex("^تأكيد وإرسال ✅$"), confirm_and_send),
                    MessageHandler(filters.Regex("^إلغاء ❌$"), fallback_to_main_menu),
                ],
                # شكوى
                PROBLEM_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_problem_details)],
                PROBLEM_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_problem_notes)],
                PROBLEM_CONFIRM: [
                    MessageHandler(filters.Regex("^تأكيد وإرسال ✅$"), confirm_and_send),
                    MessageHandler(filters.Regex("^إلغاء ❌$"), fallback_to_main_menu),
                ],
            },
            fallbacks=[
                CommandHandler("start", start),
                CommandHandler("cancel", fallback_to_main_menu),
                MessageHandler(filters.Regex("^إلغاء ❌$"), fallback_to_main_menu)
            ],
            per_user=True,
            per_chat=False,
            allow_reentry=True
        )

        app.add_handler(conv_handler)
        app.add_handler(CommandHandler("help", help_command))

        app.post_init = set_bot_commands

        application = app
        logger.info("تمت تهيئة تطبيق البوت بنجاح.")

    except Exception as e:
        logger.exception(f"فشل في تهيئة التطبيق: {e}")

# --------------------------------- WSGI entry point لِـ Gunicorn / Render ---------------------------------
def wsgi_app(environ, start_response):
    """
    نقطة دخول WSGI. عند تشغيلك مع 'gunicorn main:wsgi_app' سيُستدعى هذا.
    نحاول إعادة الـ WSGI المتاح من التطبيق إذا توفر (بعض إصدارات python-telegram-bot توفر واجهة webhooks WSGI).
    وإلا نُعيد رد 200 بسيط (يمكنك استخدام تشغيل Polling عوضاً عن Webhook بسهولة).
    """
    global application
    if application is None:
        initialize_application()

    # إذا كانت مكتبة التطبيق تدعم واجهة webhooks/Wsgi مباشرة (احتمال حسب الإصدار)، فنعيدها.
    if application is not None:
        # اختبار محفوظ: إذا كان لـ application خاصية "webhooks" قابلة للاستدعاء، نستخدمها.
        webhooks_attr = getattr(application, "webhooks", None)
        if callable(webhooks_attr):
            return webhooks_attr(environ, start_response)

    # رد بسيط للـ HTTP (مثال: صحة الخدمة)
    status = '200 OK'
    headers = [('Content-type', 'text/plain; charset=utf-8')]
    start_response(status, headers)
    return [b"OK - HR Telegram Bot is running."]

# --------------------------------- تشغيل محلي (عند تنفيذ main.py مباشرة) ---------------------------------
if __name__ == '__main__':
    if not BOT_TOKEN:
        logger.error("🚫 BOT_TOKEN غير مُعرّف. أوقف التنفيذ.")
        raise SystemExit("BOT_TOKEN is required in environment variables.")

    if application is None:
        initialize_application()

    if application is None:
        logger.error("فشل في تهيئة التطبيق خلال التشغيل.")
        raise SystemExit("Failed to initialize application.")

    # إذا وُجد رابط الويب هوك، نستخدمه (مفيد لو أردت webhooks بدل polling)
    if WEBHOOK_URL:
        logger.info(f"تشغيل باستخدام Webhook على: {WEBHOOK_URL}, port {PORT}")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            drop_pending_updates=True
        )
    else:
        logger.info("تشغيل باستخدام Polling. اضغط Ctrl+C للإيقاف.")
        application.run_polling(poll_interval=1.0)
