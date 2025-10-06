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

# --------------------------------- إعدادات التسجيل (Logging) ---------------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --------------------------------- متغيرات البيئة (Environment Variables) ---------------------------------

BOT_TOKEN: Final[str | None] = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID: Final[str | None] = os.getenv('ADMIN_CHAT_ID') 
HR_CONTACT_INFO: Final[str] = os.getenv('HR_CONTACT_INFO', 'مسؤول الموارد البشرية (يرجى تحديد جهة الاتصال)') 
WEBHOOK_URL: Final[str | None] = os.getenv('WEBHOOK_URL')
PORT: Final[int] = int(os.getenv('PORT', 8080)) 

# --------------------------------- تعريف الحالات والثوابت ---------------------------------

# الحالات (States) المستخدمة في ConversationHandler
(
    MAIN_MENU, FULL_NAME, TEAM_NAME,
    APOLOGY_TYPE, INITIATIVE_NAME, INITIATIVE_DETAILS, APOLOGY_NOTES,
    LEAVE_START_DATE, LEAVE_END_DATE, LEAVE_REASON, LEAVE_NOTES,
    PROBLEM_DETAILS, PROBLEM_DESCRIPTION, PROBLEM_NOTES,
    ADMIN_MENU, ADD_VOLUNTEER_FULL_NAME, ADD_VOLUNTEER_SELECT_TEAM
) = range(17)

# قائمة فرق العمل
TEAM_NAMES: Final[list[str]] = ["فريق الإعلام", "فريق التنسيق", "فريق الدعم اللوجستي", "إدارة المشروع"]

# --------------------------------- الدوال المساعدة (Utility Functions) ---------------------------------

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """إنشاء لوحة مفاتيح القائمة الرئيسية."""
    keyboard = [
        ["اعتذار عن مهمة 📄", "إجازة/انقطاع 🌴"],
        ["تقديم مقترح/مبادرة 💡", "ملاحظة/شكوى 🗣️"],
        ["معلومات الاتصال بالموارد البشرية 📞"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def get_team_selection_keyboard() -> ReplyKeyboardMarkup:
    """إنشاء لوحة مفاتيح لاختيار الفريق."""
    keyboard = [[team] for team in TEAM_NAMES]
    keyboard.append(["إلغاء ❌"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_confirmation_keyboard() -> ReplyKeyboardMarkup:
    """إنشاء لوحة مفاتيح التأكيد."""
    keyboard = [["تأكيد وإرسال ✅"], ["إلغاء ❌"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

async def send_to_admin(context: ContextTypes.DEFAULT_TYPE, title: str, fields: Dict[str, Any]) -> None:
    """تجميع البيانات المرسلة من المستخدم وإرسالها إلى مسؤول الموارد البشرية."""
    if not ADMIN_CHAT_ID:
        logger.error("ADMIN_CHAT_ID غير مُعرف. لا يمكن إرسال الطلب.")
        return

    message_parts = [f"<b>📢 طلب جديد: {title}</b>\n"]
    
    user_id = context.user_data.get('user_id', 'غير متوفر')
    user_name = context.user_data.get('full_name', 'مستخدم غير مسجل')
    
    message_parts.append(f"👤 مرسل الطلب: {user_name} (<code>{user_id}</code>)\n")
    
    for key, value in fields.items():
        if isinstance(value, str) and len(value) > 50:
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
        logger.info(f"تم إرسال طلب '{title}' من المستخدم {user_id} إلى الأدمن.")
    except Exception as e:
        logger.error(f"فشل إرسال رسالة إلى الأدمن {ADMIN_CHAT_ID}: {e}")

# --------------------------------- معالجات المحادثة (Conversation Handlers) ---------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ المحادثة ويعرض القائمة الرئيسية."""
    user = update.effective_user
    context.user_data.clear()
    context.user_data['user_id'] = user.id
    
    await update.message.reply_text(
        f"أهلاً بك يا {user.first_name} في نظام الموارد البشرية لفريق أبناء الأرض. كيف يمكنني خدمتك؟",
        reply_markup=get_main_menu_keyboard()
    )
    return MAIN_MENU

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يتلقى خيار المستخدم ويوجهه إلى المحادثة المناسبة."""
    text = update.message.text
    context.user_data.clear()
    context.user_data['user_id'] = update.effective_user.id
    
    if "اعتذار" in text:
        context.user_data['next_step'] = APOLOGY_TYPE
        action_name = "طلب اعتذار"
    elif "إجازة" in text:
        context.user_data['next_step'] = LEAVE_START_DATE
        action_name = "طلب إجازة"
    elif "مقترح" in text:
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
        await update.message.reply_text("خيار غير صالح. يرجى اختيار أحد الأزرار من القائمة.", reply_markup=get_main_menu_keyboard())
        return MAIN_MENU
    
    await update.message.reply_text(f"لبدء عملية {action_name}، يرجى إرسال اسمك الكامل:", reply_markup=ReplyKeyboardRemove())
    return FULL_NAME

async def handle_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يخزن الاسم الكامل وينتقل إلى خطوة اختيار الفريق."""
    full_name = update.message.text
    if len(full_name) < 3 or not all(c.isalpha() or c.isspace() or '\u0600' <= c <= '\u06FF' for c in full_name):
        await update.message.reply_text("يرجى إدخال اسم كامل وصحيح (ثلاثة أحرف على الأقل، أحرف ومسافات فقط).")
        return FULL_NAME

    context.user_data['full_name'] = full_name
    
    await update.message.reply_text(
        "شكراً لك. الآن، يرجى اختيار الفريق الذي تنتمي إليه:",
        reply_markup=get_team_selection_keyboard()
    )
    return TEAM_NAME

async def handle_team_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يخزن اسم الفريق وينتقل إلى الخطوة الحقيقية التالية."""
    team_name = update.message.text
    if team_name == "إلغاء ❌":
        return await fallback_to_main_menu(update, context)

    if team_name not in TEAM_NAMES:
        await update.message.reply_text("يرجى اختيار فريق من القائمة أو الضغط على إلغاء.", reply_markup=get_team_selection_keyboard())
        return TEAM_NAME
        
    context.user_data['team_name'] = team_name
    next_step = context.user_data.pop('next_step', MAIN_MENU)

    if next_step == APOLOGY_TYPE:
        await update.message.reply_text(
            "ما نوع الاعتذار الذي تود تقديمه؟",
            reply_markup=ReplyKeyboardMarkup([["تأخير عن مهمة", "تأخير عن اجتماع"], ["عدم حضور مهمة", "عدم حضور اجتماع"]], resize_keyboard=True, one_time_keyboard=True)
        )
        return APOLOGY_TYPE
    elif next_step == LEAVE_START_DATE:
        await update.message.reply_text("يرجى إرسال تاريخ بدء الإجازة/الانقطاع (بالصيغة: YYYY-MM-DD):", reply_markup=ReplyKeyboardRemove())
        return LEAVE_START_DATE
    elif next_step == INITIATIVE_NAME:
        await update.message.reply_text("يرجى إدخال اسم مقترحك/مبادرتك بإيجاز:", reply_markup=ReplyKeyboardRemove())
        return INITIATIVE_NAME
    elif next_step == PROBLEM_DETAILS:
        await update.message.reply_text("يرجى وصف المشكلة/الشكوى بوضوح:", reply_markup=ReplyKeyboardRemove())
        return PROBLEM_DETAILS
    
    return await fallback_to_main_menu(update, context)

# --- مسارات الاعتذار (Apology) ---
async def handle_apology_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['apology_type'] = update.message.text
    await update.message.reply_text("يرجى ذكر سبب الاعتذار بوضوح وإيجاز:")
    return INITIATIVE_DETAILS 

async def handle_apology_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['apology_reason'] = update.message.text
    await update.message.reply_text("هل لديك أي ملاحظات إضافية تود إضافتها؟ (اكتب 'لا' إذا لم يكن لديك):")
    return APOLOGY_NOTES

async def handle_apology_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['apology_notes'] = update.message.text
    
    data = context.user_data
    summary = (
        f"ملخص طلب الاعتذار:\n"
        f"• الاسم: {data.get('full_name')}\n"
        f"• الفريق: {data.get('team_name')}\n"
        f"• النوع: {data.get('apology_type')}\n"
        f"• السبب: {data.get('apology_reason')}\n"
        f"• ملاحظات: {data.get('apology_notes')}\n"
        "\nهل أنت متأكد من إرسال هذا الطلب؟"
    )
    
    await update.message.reply_text(summary, reply_markup=get_confirmation_keyboard())
    return APOLOGY_NOTES + 1 

# --- مسارات الإجازة/الانقطاع (Leave) ---
async def handle_leave_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['leave_start_date'] = update.message.text
    await update.message.reply_text("يرجى إرسال تاريخ انتهاء الإجازة/الانقطاع (بالصيغة: YYYY-MM-DD):")
    return LEAVE_END_DATE

async def handle_leave_end_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['leave_end_date'] = update.message.text
    await update.message.reply_text("يرجى ذكر سبب الإجازة/الانقطاع بوضوح:")
    return LEAVE_REASON

async def handle_leave_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['leave_reason'] = update.message.text
    await update.message.reply_text("هل لديك أي ترتيبات أو ملاحظات إضافية تود إضافتها؟ (اكتب 'لا' إذا لم يكن لديك):")
    return LEAVE_NOTES

async def handle_leave_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['leave_notes'] = update.message.text
    
    data = context.user_data
    summary = (
        f"ملخص طلب الإجازة/الانقطاع:\n"
        f"• الاسم: {data.get('full_name')}\n"
        f"• الفريق: {data.get('team_name')}\n"
        f"• تاريخ البدء: {data.get('leave_start_date')}\n"
        f"• تاريخ الانتهاء: {data.get('leave_end_date')}\n"
        f"• السبب: {data.get('leave_reason')}\n"
        f"• ملاحظات: {data.get('leave_notes')}\n"
        "\nهل أنت متأكد من إرسال هذا الطلب؟"
    )
    
    await update.message.reply_text(summary, reply_markup=get_confirmation_keyboard())
    return LEAVE_NOTES + 1 

# --- مسارات المقترح (Initiative) ---
async def handle_initiative_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['initiative_name'] = update.message.text
    await update.message.reply_text("يرجى شرح مقترحك/مبادرتك بالتفصيل:", reply_markup=ReplyKeyboardRemove())
    return INITIATIVE_DETAILS

async def handle_initiative_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['initiative_details'] = update.message.text
    
    data = context.user_data
    summary = (
        f"ملخص طلب المقترح/المبادرة:\n"
        f"• الاسم: {data.get('full_name')}\n"
        f"• الفريق: {data.get('team_name')}\n"
        f"• اسم المقترح: {data.get('initiative_name')}\n"
        f"• التفاصيل:\n<pre>{data.get('initiative_details')}</pre>"
        f"\nهل أنت متأكد من إرسال هذا الطلب؟"
    )
    
    await update.message.reply_text(summary, parse_mode='HTML', reply_markup=get_confirmation_keyboard())
    return APOLOGY_NOTES + 1 # حالة تأكيد عامة

# --- مسارات الشكوى (Problem) ---
async def handle_problem_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['problem_description'] = update.message.text
    await update.message.reply_text("هل لديك أي ملاحظات إضافية أو أدلة (مثل رابط أو لقطة شاشة)؟ (اكتب 'لا' إذا لم يكن لديك):")
    return PROBLEM_NOTES

async def handle_problem_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['problem_notes'] = update.message.text
    
    data = context.user_data
    summary = (
        f"ملخص طلب المشكلة/الشكوى:\n"
        f"• الاسم: {data.get('full_name')}\n"
        f"• الفريق: {data.get('team_name')}\n"
        f"• الوصف: {data.get('problem_description')}\n"
        f"• ملاحظات/أدلة: {data.get('problem_notes')}\n"
        "\nهل أنت متأكد من إرسال هذا الطلب؟"
    )
    
    await update.message.reply_text(summary, reply_markup=get_confirmation_keyboard())
    return PROBLEM_NOTES + 1 


# --- معالج الإرسال والتأكيد المشترك (Common Confirmation) ---
async def confirm_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يتلقى أمر 'تأكيد وإرسال' ويرسل الطلب إلى الأدمن."""
    if update.message.text != "تأكيد وإرسال ✅":
        return await fallback_to_main_menu(update, context)

    data = context.user_data
    title = "غير محدد"
    fields = {}
    
    # تحديد نوع الطلب بناءً على البيانات المخزنة
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
            "التفاصيل": data.get('initiative_details'), # تم إضافة فاصلة (comma) هنا
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
        f"✅ تم إرسال طلبك ({title}) بنجاح إلى مسؤول الموارد البشرية للمتابعة.\nشكراً لك.",
        reply_markup=get_main_menu_keyboard()
    )
    
    context.user_data.clear()
    return MAIN_MENU

async def fallback_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالج الإلغاء/الإيقاف لأي محادثة جارية."""
    await update.message.reply_text(
        "❌ تم إلغاء العملية. يمكنك البدء من جديد من القائمة الرئيسية.",
        reply_markup=get_main_menu_keyboard()
    )
    context.user_data.clear()
    return MAIN_MENU

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض قائمة الأوامر المتاحة."""
    help_text = (
        "مرحباً بك في نظام الموارد البشرية لفريق أبناء الأرض.\n"
        "إليك قائمة الأوامر المتاحة:\n"
        "• /start - بدء المحادثة والعودة للقائمة الرئيسية.\n"
        "• /help - عرض هذه الرسالة.\n"
        "\n"
        "يمكنك استخدام الأزرار في القائمة لتقديم الطلبات."
    )
    await update.message.reply_text(help_text, reply_markup=get_main_menu_keyboard())

# -------------------------- FIX: Refactor set_bot_commands for post_init --------------------------

async def set_bot_commands(app: Application) -> None:
    """تعيين قائمة الأوامر للبوت باستخدام post_init لحل مشكلة JobQueue في بيئة Webhook."""
    bot_commands = [
        BotCommand("start", "بدء المحادثة والعودة للقائمة الرئيسية"),
        BotCommand("help", "عرض المساعدة والأوامر المتاحة"),
    ]
    await app.bot.set_my_commands(bot_commands)

# --------------------------------- إعداد البوت (Initialization) ---------------------------------

application: Optional[Application] = None

def initialize_application():
    """تهيئة تطبيق python-telegram-bot والـ Handlers."""
    global application

    if not BOT_TOKEN:
        logger.error("🚫 BOT_TOKEN غير مُعرف في متغيرات البيئة. لا يمكن بدء البوت.")
        return

    try:
        app = Application.builder().token(BOT_TOKEN).build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                MAIN_MENU: [
                    MessageHandler(filters.Regex("^(اعتذار عن مهمة|إجازة/انقطاع|تقديم مقترح/مبادرة|ملاحظة/شكوى|معلومات الاتصال بالموارد البشرية)"), main_menu),
                ],
                FULL_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_full_name),
                ],
                TEAM_NAME: [
                    MessageHandler(filters.Regex(f"^({'|'.join(TEAM_NAMES)}|إلغاء ❌)$"), handle_team_name),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_team_name), 
                ],
                
                # حالات الاعتذار
                APOLOGY_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_apology_type)],
                INITIATIVE_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_apology_reason)], 
                APOLOGY_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_apology_notes)],
                
                # حالات الإجازة
                LEAVE_START_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leave_start_date)],
                LEAVE_END_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leave_end_date)],
                LEAVE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leave_reason)],
                LEAVE_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leave_notes)],

                # حالات المقترح والشكوى
                INITIATIVE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_initiative_name)],
                PROBLEM_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_problem_details)],
                PROBLEM_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_problem_notes)],

                # حالات التأكيد العامة (APOLOGY_NOTES + 1 هي 7, LEAVE_NOTES + 1 هي 11, PROBLEM_NOTES + 1 هي 14)
                APOLOGY_NOTES + 1: [
                    MessageHandler(filters.Regex("^تأكيد وإرسال ✅$"), confirm_and_send),
                    MessageHandler(filters.Regex("^إلغاء ❌$"), fallback_to_main_menu),
                ],
                LEAVE_NOTES + 1: [
                    MessageHandler(filters.Regex("^تأكيد وإرسال ✅$"), confirm_and_send),
                    MessageHandler(filters.Regex("^إلغاء ❌$"), fallback_to_main_menu),
                ],
                PROBLEM_NOTES + 1: [
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

        # استخدام post_init بدلاً من job_queue.run_once لحل مشكلة 'NoneType' في بيئة Webhook/Gunicorn.
        app.post_init = set_bot_commands

        application = app
        logger.info("تمت تهيئة تطبيق البوت بنجاح.")

    except Exception as e:
        logger.error(f"فشل في تهيئة التطبيق: {e}")

# --------------------------------- دالة WSGI لـ Render ---------------------------------
def wsgi_app(environ, start_response):
    """نقطة الدخول (Entry Point) لتطبيق WSGI المستخدم من قبل Gunicorn و Render."""
    global application
    
    if application is None:
        initialize_application()

    if application is None:
        status = '500 INTERNAL SERVER ERROR'
        headers = [('Content-type', 'text/plain')]
        start_response(status, headers)
        return [b"Application not initialized or BOT_TOKEN is missing."]
        
    return application.webhooks(environ, start_response)


# --------------------------------- دالة التشغيل المحلية (للتطوير فقط) ---------------------------------
if __name__ == '__main__':
    if BOT_TOKEN:
        if application is None:
            initialize_application()
            
        if application:
            if WEBHOOK_URL:
                logger.info(f"يتم إعداد الويب هوك على المنفذ: {PORT}")
                application.run_webhook( 
                    listen="0.0.0.0",
                    port=PORT,
                    url_path=BOT_TOKEN,
                    webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
                    drop_pending_updates=True
                )
            else:
                logger.info("يتم التشغيل محلياً باستخدام Polling. اضغط Ctrl+C للإيقاف.")
                application.run_polling(poll_interval=1.0)
    else:
        logger.error("🚫 BOT_TOKEN غير مُعرف. يرجى تعيينه في متغيرات البيئة.")

