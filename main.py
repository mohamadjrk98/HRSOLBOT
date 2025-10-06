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

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
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

    await update.message.reply_text(f"لبدء {action_name}، أرسل اسمك الكامل:", reply_markup=ReplyKeyboardRemove())
    return FULL_NAME

async def handle_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    full_name = (update.message.text or "").strip()
    if len(full_name) < 3:
        await update.message.reply_text("يرجى إدخال اسم كامل مكوّن من 3 أحرف على الأقل.")
        return FULL_NAME

    context.user_data['full_name'] = full_name
    await update.message.reply_text("شكراً. الآن اختر فريقك:", reply_markup=get_team_selection_keyboard())
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

    if next_step == APOLOGY_TYPE:
        await update.message.reply_text(
            "ما نوع الاعتذار الذي تود تقديمه؟",
            reply_markup=ReplyKeyboardMarkup(
                [["تأخير عن مهمة", "تأخير عن اجتماع"], ["عدم حضور مهمة", "عدم حضور اجتماع"], ["إلغاء ❌"]],
                resize_keyboard=True, one_time_keyboard=True
            )
        )
        return APOLOGY_TYPE
    elif next_step == LEAVE_START_DATE:
        await update.message.reply_text("أرسل تاريخ بدء الإجازة (YYYY-MM-DD):", reply_markup=ReplyKeyboardRemove())
        return LEAVE_START_DATE
    elif next_step == INITIATIVE_NAME:
        await update.message.reply_text("أدخل اسم المقترح/المبادرة بإيجاز:", reply_markup=ReplyKeyboardRemove())
        return INITIATIVE_NAME
    elif next_step == PROBLEM_DETAILS:
        await update.message.reply_text("وصف المشكلة/الشكوى:", reply_markup=ReplyKeyboardRemove())
        return PROBLEM_DETAILS
    return await fallback_to_main_menu(update, context)

# --- Handlers أخرى: اعتذار ---
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

# --- Handlers أخرى: إجازة ---
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

# --- Handlers أخرى: مبادرة ---
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

# --- Handlers أخرى: شكوى/ملاحظة ---
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

# --- Confirm & Send ---
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
    await update.message.reply
INITIATIVE_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_and_send)],
            PROBLEM_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_problem_details)],
            PROBLEM_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_problem_notes)],
            PROBLEM_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_and_send)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))

    logger.info("✅ البوت جاهز ويعمل باستخدام Polling. بدء التشغيل...")
    application.run_polling()
