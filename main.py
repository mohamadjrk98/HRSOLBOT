import logging
import os
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

# إعدادات التسجيل (Logging)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# الحالات (States) المستخدمة في ConversationHandler
(MAIN_MENU, FIRST_NAME, LAST_NAME, TEAM_NAME, 
 APOLOGY_TYPE, INITIATIVE_NAME, APOLOGY_REASON, APOLOGY_NOTES,
 LEAVE_START_DATE, LEAVE_END_DATE, LEAVE_REASON, LEAVE_NOTES,
 FEEDBACK_MESSAGE, PROBLEM_DESCRIPTION, PROBLEM_NOTES) = range(15)

# متغيرات البيئة (Environment Variables)
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')

# متغيرات خاصة بـ Webhook Render
WEBHOOK_URL = os.getenv('WEBHOOK_URL')  # مثال: https://your-bot-name.onrender.com
PORT = int(os.environ.get('PORT', '5000')) # المنفذ الذي سيتم الاستماع عليه

def generate_request_id():
    """توليد رقم طلب فريد"""
    return f"REQ{int(time.time())}"

def get_request_title(request_type):
    """جلب عنوان الطلب بناءً على نوعه"""
    titles = {
        'apology': 'طلب الاعتذار',
        'leave': 'طلب الإجازة',
        'problem': 'بلاغ المشكلة',
        'feedback': 'الاقتراح/الملاحظة'
    }
    return titles.get(request_type, 'طلب')

# --------------------------------- الدوال الأساسية ---------------------------------

# (باقي الدوال: start, main_menu_choice, first_name, last_name, team_name, apology_type, initiative_name, 
# apology_reason, apology_notes, leave_start_date, leave_end_date, leave_reason, leave_notes, 
# problem_description, problem_notes, feedback_message, handle_admin_action, back_to_menu, new_request_handler, cancel)
# تبقى كما هي بدون تغيير، لضمان أن الكود يكون كاملاً ومحدثاً، سأعيدها في الكتلة النهائية:

# --------------------------------- الدوال الأساسية ---------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """البداية - عرض القائمة الرئيسية"""
    query = update.callback_query
    if query:
        await query.answer()
        user = query.from_user
        message = query.message
    else:
        user = update.effective_user
        message = update.message

    keyboard = [
        [InlineKeyboardButton("📝 طلب اعتذار", callback_data='apology')],
        [InlineKeyboardButton("🏖️ طلب إجازة", callback_data='leave')],
        [InlineKeyboardButton("🔧 قسم حل المشاكل", callback_data='problem')],
        [InlineKeyboardButton("💡 اقتراحات وملاحظات", callback_data='feedback')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f'أهلاً {user.first_name}! 👋\n\n'
        'أنا بوت طلبات المتطوعين.\n'
        'كيف يمكنني مساعدتك اليوم؟\n\n'
        'لإلغاء الطلب في أي وقت، أرسل /cancel'
    )

    if query:
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await message.reply_text(text, reply_markup=reply_markup, reply_to_message_id=None)

    return MAIN_MENU

# --------------------------------- دوال القوائم والمسارات ---------------------------------

async def main_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة اختيار القائمة الرئيسية"""
    query = update.callback_query
    await query.answer()

    choice = query.data
    context.user_data.clear() # مسح البيانات السابقة عند بدء طلب جديد
    context.user_data['request_type'] = choice
    context.user_data['request_id'] = generate_request_id()

    keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if choice == 'feedback':
        await query.edit_message_text(
            '💡 اقتراحات وملاحظات\n\n'
            'نسعد بسماع آرائك واقتراحاتك!\n'
            'الرجاء كتابة اقتراحك أو ملاحظتك:',
            reply_markup=reply_markup
        )
        return FEEDBACK_MESSAGE

    elif choice == 'problem':
        await query.edit_message_text(
            '🔧 قسم حل المشاكل\n\n'
            'الرجاء وصف المشكلة التي تواجهها بوضوح:',
            reply_markup=reply_markup
        )
        return PROBLEM_DESCRIPTION

    # مسار الاعتذار والإجازة يتطلب الاسم والفريق أولاً
    await query.edit_message_text(
        'الرجاء إدخال اسمك الأول:',
        reply_markup=reply_markup
    )
    return FIRST_NAME

# --------------------------------- مسار الإسم والفريق ---------------------------------

async def first_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ الاسم الأول وطلب الكنية"""
    context.user_data['first_name'] = update.message.text

    keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f'أهلاً {update.message.text}!\n\n'
        'الرجاء إدخال الكنية (اسم العائلة):',
        reply_markup=reply_markup
    )
    return LAST_NAME


async def last_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ الكنية وطلب اسم الفريق"""
    context.user_data['last_name'] = update.message.text

    keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        'ما هو الفريق الذي تنتمي إليه؟\n'
        '(مثال: فريق الدعم الأول، الدعم الثاني، الخ)',
        reply_markup=reply_markup
    )
    return TEAM_NAME


async def team_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ اسم الفريق والانتقال حسب نوع الطلب"""
    context.user_data['team_name'] = update.message.text
    request_type = context.user_data.get('request_type')

    if request_type == 'apology':
        keyboard = [
            [InlineKeyboardButton("اجتماع", callback_data='meeting')],
            [InlineKeyboardButton("مبادرة", callback_data='initiative')],
            [InlineKeyboardButton("آخر", callback_data='other')],
            [InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            '📝 طلب اعتذار\n\n'
            'ما هو نوع الفعالية/الاعتذار؟',
            reply_markup=reply_markup
        )
        return APOLOGY_TYPE

    elif request_type == 'leave':
        keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            '🏖️ طلب إجازة\n\n'
            '📌 **ملاحظة هامة:** مدة الإجازة المسموحة للمتطوع خلال السنة هي **شهر واحد فقط** للامتحانات و**الظروف القاهرة**.\n\n'
            'الرجاء إدخال **تاريخ بدء الإجازة**:\n'
            '(يُرجى استخدام صيغة واضحة مثل: 2025-11-01)',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return LEAVE_START_DATE

    return MAIN_MENU

# --------------------------------- مسار طلب الاعتذار ---------------------------------

async def apology_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ نوع الفعالية والتوجيه حسب نوعها (مبادرة أم غيرها)"""
    query = update.callback_query
    await query.answer()

    type_map = {
        'meeting': 'اجتماع',
        'initiative': 'مبادرة',
        'other': 'آخر'
    }

    type_choice = query.data
    context.user_data['apology_type'] = type_map.get(type_choice, type_choice)

    keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # إذا اختار المتطوع "مبادرة"، ننتقل لخطوة طلب اسم المبادرة
    if type_choice == 'initiative':
        await query.edit_message_text(
            'الرجاء إدخال **اسم المبادرة** التي تعتذر عنها:',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return INITIATIVE_NAME
    else:
        # باقي الخيارات (اجتماع، آخر) تنتقل مباشرة لسبب الاعتذار
        await query.edit_message_text(
            f'تم اختيار: {context.user_data["apology_type"]}\n\n'
            'الرجاء كتابة سبب الاعتذار بالتفصيل:',
            reply_markup=reply_markup
        )
        return APOLOGY_REASON

async def initiative_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ اسم المبادرة وطلب سبب الاعتذار"""
    context.user_data['initiative_name'] = update.message.text

    keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f'المبادرة: {update.message.text}\n\n'
        'الرجاء كتابة سبب الاعتذار بالتفصيل:',
        reply_markup=reply_markup
    )
    return APOLOGY_REASON


async def apology_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ سبب الاعتذار وطلب الملاحظات"""
    context.user_data['apology_reason'] = update.message.text

    keyboard = [
        [InlineKeyboardButton("⏭️ تخطي", callback_data='skip_apology_notes')],
        [InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        'هل لديك أي ملاحظات إضافية بخصوص الاعتذار؟\n'
        '(اكتب ملاحظاتك أو اضغط تخطي)',
        reply_markup=reply_markup
    )
    return APOLOGY_NOTES


async def apology_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ الملاحظات وإرسال الطلب للمدير"""
    message = update.message
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        context.user_data['apology_notes'] = 'لا توجد'
        message = query.message
    else:
        context.user_data['apology_notes'] = update.message.text


    user = update.effective_user
    request_id = context.user_data.get('request_id', 'N/A')
    user_id = user.id
    request_type = context.user_data.get('request_type', 'apology')
    first_name = context.user_data.get('first_name', 'غير محدد')
    last_name = context.user_data.get('last_name', 'غير محدد')
    team_name = context.user_data.get('team_name', 'غير محدد')
    apology_type = context.user_data.get('apology_type', 'غير محدد')
    apology_reason = context.user_data.get('apology_reason', 'غير محدد')
    apology_notes = context.user_data.get('apology_notes', 'لا توجد')

    # إضافة اسم المبادرة إذا كانت موجودة
    initiative_name_val = context.user_data.get('initiative_name')
    if initiative_name_val:
        details_line = f'• النوع: {apology_type} ({initiative_name_val})\n'
        admin_type_line = f'• نوع الاعتذار: {apology_type} ({initiative_name_val})\n'
    else:
        details_line = f'• النوع: {apology_type}\n'
        admin_type_line = f'• نوع الاعتذار: {apology_type}\n'

    volunteer_message = (
        f'✅ **تم استلام طلب الاعتذار!**\n\n'
        f'🔖 رقم الطلب: `{request_id}`\n\n'
        f'📋 **ملخص الطلب:**\n'
        f'• الاسم: {first_name} {last_name}\n'
        f'• الفريق: {team_name}\n'
        f'{details_line}'
        f'• السبب: {apology_reason}\n'
        f'• ملاحظات: {apology_notes}\n\n'
        f'**أثرك موجود دائماً.. شكراً لأنك معنا 💚**\n\n'
        f'سيتم مراجعة طلبك قريباً.'
    )

    admin_message = (
        f'📝 **طلب اعتذار جديد**\n'
        f'━━━━━━━━━━━━━━━━━\n'
        f'🔖 رقم الطلب: `{request_id}`\n'
        f'👤 الاسم: {first_name} {last_name}\n'
        f'👥 الفريق: {team_name}\n'
        f'🆔 المعرف: @{user.username or "لا يوجد"}\n'
        f'🆔 رقم المستخدم: {user_id}\n\n'
        f'📋 **التفاصيل:**\n'
        f'{admin_type_line}'
        f'• سبب الاعتذار: {apology_reason}\n'
        f'• ملاحظات: {apology_notes}\n'
        f'━━━━━━━━━━━━━━━━━'
    )

    # أزرار الإجراء للمشرف
    admin_keyboard = [
        [
            InlineKeyboardButton("✅ موافقة", callback_data=f'action|approve|{request_type}|{request_id}|{user_id}'),
            InlineKeyboardButton("❌ رفض الطلب", callback_data=f'action|reject|{request_type}|{request_id}|{user_id}')
        ]
    ]
    admin_reply_markup = InlineKeyboardMarkup(admin_keyboard)

    keyboard = [
        [InlineKeyboardButton("📝 طلب جديد", callback_data='new_request')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # إرسال رسالة التأكيد للمتطوع
    if update.callback_query:
        await message.edit_text(volunteer_message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await message.reply_text(volunteer_message, reply_markup=reply_markup, parse_mode='Markdown')

    # إرسال رسالة للمدير
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_message,
            reply_markup=admin_reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"خطأ في إرسال الرسالة للمدير: {e}")

    context.user_data.clear()
    return ConversationHandler.END

# --------------------------------- مسار طلب الإجازة ---------------------------------

async def leave_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ تاريخ بدء الإجازة وطلب تاريخ الانتهاء"""
    context.user_data['leave_start_date'] = update.message.text

    keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f'تاريخ البدء: {update.message.text}\n\n'
        'الرجاء إدخال **تاريخ انتهاء الإجازة**:',
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return LEAVE_END_DATE

async def leave_end_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ تاريخ انتهاء الإجازة وطلب السبب"""
    context.user_data['leave_end_date'] = update.message.text

    keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f'تاريخ الانتهاء: {update.message.text}\n\n'
        'الرجاء كتابة سبب طلب الإجازة بوضوح:',
        reply_markup=reply_markup
    )
    return LEAVE_REASON


async def leave_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ سبب الإجازة وطلب الملاحظات"""
    context.user_data['leave_reason'] = update.message.text

    keyboard = [
        [InlineKeyboardButton("⏭️ تخطي", callback_data='skip_leave_notes')],
        [InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        'هل لديك أي ملاحظات إضافية بخصوص الإجازة؟\n'
        '(اكتب ملاحظاتك أو اضغط تخطي)',
        reply_markup=reply_markup
    )
    return LEAVE_NOTES


async def leave_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ الملاحظات وإرسال الطلب للمدير"""
    message = update.message
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        context.user_data['leave_notes'] = 'لا توجد'
        message = query.message
    else:
        context.user_data['leave_notes'] = update.message.text

    user = update.effective_user
    request_id = context.user_data.get('request_id', 'N/A')
    user_id = user.id
    request_type = context.user_data.get('request_type', 'leave')
    first_name = context.user_data.get('first_name', 'غير محدد')
    last_name = context.user_data.get('last_name', 'غير محدد')
    team_name = context.user_data.get('team_name', 'غير محدد')
    # استخدام التواريخ الجديدة
    leave_start_date = context.user_data.get('leave_start_date', 'غير محدد')
    leave_end_date = context.user_data.get('leave_end_date', 'غير محدد')
    leave_reason = context.user_data.get('leave_reason', 'غير محدد')
    leave_notes = context.user_data.get('leave_notes', 'لا توجد')

    volunteer_message = (
        f'✅ **تم استلام طلب الإجازة!**\n\n'
        f'🔖 رقم الطلب: `{request_id}`\n\n'
        f'📋 **ملخص الطلب:**\n'
        f'• الاسم: {first_name} {last_name}\n'
        f'• الفريق: {team_name}\n'
        f'• تاريخ البدء: {leave_start_date}\n' # مُحدَّث
        f'• تاريخ الانتهاء: {leave_end_date}\n' # مُحدَّث
        f'• السبب: {leave_reason}\n'
        f'• ملاحظات: {leave_notes}\n\n'
        f'**أثرك موجود دائماً.. شكراً لأنك معنا 💚**\n\n'
        f'سيتم مراجعة طلبك قريباً.'
    )

    admin_message = (
        f'🏖️ **طلب إجازة جديد**\n'
        f'━━━━━━━━━━━━━━━━━\n'
        f'🔖 رقم الطلب: `{request_id}`\n'
        f'👤 الاسم: {first_name} {last_name}\n'
        f'👥 الفريق: {team_name}\n'
        f'🆔 المعرف: @{user.username or "لا يوجد"}\n'
        f'🆔 رقم المستخدم: {user_id}\n\n'
        f'📋 **التفاصيل:**\n'
        f'• تاريخ بدء الإجازة: {leave_start_date}\n' # مُحدَّث
        f'• تاريخ انتهاء الإجازة: {leave_end_date}\n' # مُحدَّث
        f'• سبب الإجازة: {leave_reason}\n'
        f'• ملاحظات: {leave_notes}\n'
        f'━━━━━━━━━━━━━━━━━'
    )

    # أزرار الإجراء للمشرف
    admin_keyboard = [
        [
            InlineKeyboardButton("✅ موافقة", callback_data=f'action|approve|{request_type}|{request_id}|{user_id}'),
            InlineKeyboardButton("❌ رفض الطلب", callback_data=f'action|reject|{request_type}|{request_id}|{user_id}')
        ]
    ]
    admin_reply_markup = InlineKeyboardMarkup(admin_keyboard)

    keyboard = [
        [InlineKeyboardButton("📝 طلب جديد", callback_data='new_request')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # إرسال رسالة التأكيد للمتطوع
    if update.callback_query:
        await message.edit_text(volunteer_message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await message.reply_text(volunteer_message, reply_markup=reply_markup, parse_mode='Markdown')

    # إرسال رسالة للمدير
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_message,
            reply_markup=admin_reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"خطأ في إرسال الرسالة للمدير: {e}")

    context.user_data.clear()
    return ConversationHandler.END

# --------------------------------- مسار المشاكل ---------------------------------

async def problem_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ وصف المشكلة وطلب الملاحظات"""
    context.user_data['problem_description'] = update.message.text

    keyboard = [
        [InlineKeyboardButton("⏭️ تخطي", callback_data='skip_problem_notes')],
        [InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        'هل لديك أي ملاحظات إضافية أو معلومات تساعد في حل المشكلة؟\n'
        '(اكتب ملاحظاتك أو اضغط تخطي)',
        reply_markup=reply_markup
    )
    return PROBLEM_NOTES


async def problem_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ الملاحظات وإرسال البلاغ للمدير"""
    message = update.message
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        context.user_data['problem_notes'] = 'لا توجد'
        message = query.message
    else:
        context.user_data['problem_notes'] = update.message.text

    user = update.effective_user
    request_id = context.user_data.get('request_id', 'N/A')
    user_id = user.id
    request_type = context.user_data.get('request_type', 'problem')
    problem_description = context.user_data.get('problem_description', 'غير محدد')
    problem_notes = context.user_data.get('problem_notes', 'لا توجد')

    volunteer_message = (
        f'✅ **تم استلام بلاغ المشكلة!**\n\n'
        f'🔖 رقم البلاغ: `{request_id}`\n\n'
        f'📋 **ملخص البلاغ:**\n'
        f'• المشكلة: {problem_description}\n'
        f'• ملاحظات: {problem_notes}\n\n'
        f'**أثرك موجود دائماً.. شكراً لأنك معنا 💚**\n\n'
        f'سيتم العمل على حل المشكلة قريباً.'
    )

    admin_message = (
        f'🔧 **بلاغ مشكلة جديد**\n'
        f'━━━━━━━━━━━━━━━━━\n'
        f'🔖 رقم البلاغ: `{request_id}`\n'
        f'👤 من: {user.first_name} {user.last_name or ""}\n'
        f'🆔 المعرف: @{user.username or "لا يوجد"}\n'
        f'🆔 رقم المستخدم: {user_id}\n\n'
        f'📋 **التفاصيل:**\n'
        f'• وصف المشكلة: {problem_description}\n'
        f'• ملاحظات: {problem_notes}\n'
        f'━━━━━━━━━━━━━━━━━'
    )

    # أزرار الإجراء للمشرف
    admin_keyboard = [
        [
            InlineKeyboardButton("✅ موافقة", callback_data=f'action|approve|{request_type}|{request_id}|{user_id}'),
            InlineKeyboardButton("❌ رفض الطلب", callback_data=f'action|reject|{request_type}|{request_id}|{user_id}')
        ]
    ]
    admin_reply_markup = InlineKeyboardMarkup(admin_keyboard)

    keyboard = [
        [InlineKeyboardButton("📝 طلب جديد", callback_data='new_request')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # إرسال رسالة التأكيد للمتطوع
    if update.callback_query:
        await message.edit_text(volunteer_message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await message.reply_text(volunteer_message, reply_markup=reply_markup, parse_mode='Markdown')

    # إرسال رسالة للمدير
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_message,
            reply_markup=admin_reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"خطأ في إرسال الرسالة للمدير: {e}")

    context.user_data.clear()
    return ConversationHandler.END

# --------------------------------- مسار الاقتراحات ---------------------------------

async def feedback_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """استلام الاقتراح وإرساله للمدير"""
    feedback = update.message.text
    user = update.effective_user
    request_id = context.user_data.get('request_id', 'N/A')
    user_id = user.id
    request_type = context.user_data.get('request_type', 'feedback')

    volunteer_message = (
        f'✅ **شكراً لك على اقتراحك!**\n\n'
        f'🔖 رقم الرسالة: `{request_id}`\n\n'
        f'**أثرك موجود دائماً.. شكراً لأنك معنا 💚**\n\n'
        f'تم إرسال رسالتك وسنقوم بمراجعتها قريباً.'
    )

    admin_message = (
        f'💡 **اقتراح/ملاحظة جديدة**\n'
        f'━━━━━━━━━━━━━━━━━\n'
        f'🔖 رقم الرسالة: `{request_id}`\n'
        f'👤 من: {user.first_name} {user.last_name or ""}\n'
        f'🆔 المعرف: @{user.username or "لا يوجد"}\n'
        f'🆔 رقم المستخدم: {user_id}\n\n'
        f'📝 **الرسالة:**\n{feedback}\n'
        f'━━━━━━━━━━━━━━━━━'
    )

    # أزرار الإجراء للمشرف - (الاقتراحات لا تحتاج موافقة/رفض بالضرورة، لكن نضيفها لتوحيد الواجهة)
    admin_keyboard = [
        [
            InlineKeyboardButton("✅ تم الاطلاع", callback_data=f'action|approve|{request_type}|{request_id}|{user_id}'),
            InlineKeyboardButton("❌ يتطلب متابعة", callback_data=f'action|reject|{request_type}|{request_id}|{user_id}')
        ]
    ]
    admin_reply_markup = InlineKeyboardMarkup(admin_keyboard)

    keyboard = [
        [InlineKeyboardButton("📝 طلب جديد", callback_data='new_request')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(volunteer_message, reply_markup=reply_markup, parse_mode='Markdown')

    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_message,
            reply_markup=admin_reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"خطأ في إرسال الرسالة للمدير: {e}")

    context.user_data.clear()
    return ConversationHandler.END

# --------------------------------- دوال التحكم والإجراءات ---------------------------------

async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة أزرار الموافقة/الرفض في رسالة المشرف"""
    query = update.callback_query
    await query.answer()

    # parse callback_data: action|approve/reject|request_type|request_id|user_id
    data = query.data.split('|')
    action = data[1]
    request_type = data[2]
    request_id = data[3]
    user_id = data[4]

    admin_user = query.from_user
    request_title = get_request_title(request_type)

    # 1. إشعار المستخدم الأصلي
    try:
        if action == 'approve':
            user_notification = f'✅ تهانينا! تمت **الموافقة** على {request_title} الخاص بك برقم `{request_id}`.'
        else:
            user_notification = (
                f'❌ نعتذر! تم **رفض** {request_title} الخاص بك برقم `{request_id}`.\n'
                f'للاستعلام عن السبب، يرجى **مراسلة الموارد البشرية (HR)**.'
            )

        await context.bot.send_message(
            chat_id=user_id,
            text=user_notification,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"خطأ في إرسال الإشعار للمستخدم {user_id}: {e}")

    # 2. تحديث رسالة المشرف (الرسالة الأصلية)
    status_text = "تمت الموافقة ✅" if action == 'approve' else "تم الرفض ❌"

    # تحديث محتوى الرسالة الأصلية للمشرف
    original_text = query.message.text
    updated_text = (
        f"{original_text}\n\n"
        f"**━━━━━━━━━━━━━━━━━**\n"
        f"**📌 حالة الطلب:** {status_text}\n"
        f"**✍️ بواسطة:** {admin_user.first_name} (@{admin_user.username or 'لا يوجد'})"
    )

    try:
        await query.edit_message_text(
            text=updated_text,
            reply_markup=None, # إزالة الأزرار
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"خطأ في تحديث رسالة المشرف: {e}")


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """العودة للقائمة الرئيسية"""
    query = update.callback_query
    if query:
        await query.answer()

    context.user_data.clear()
    return await start(update, context)


async def new_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة زر طلب جديد"""
    return await start(update, context)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """إلغاء المحادثة"""
    await update.message.reply_text(
        '❌ **تم إلغاء الطلب.**\n'
        'يمكنك البدء من جديد بإرسال /start',
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    context.user_data.clear()
    return ConversationHandler.END


def main_setup() -> Application:
    """إعداد كائن التطبيق (Application) وإعادة تعريفه ليتم تشغيله بواسطة Gunicorn"""
    if not BOT_TOKEN:
        logger.error("خطأ: BOT_TOKEN غير موجود!")
        # يمكن إرجاع Application وهمي أو إثارة خطأ هنا
        raise ValueError("BOT_TOKEN environment variable not set.")

    if not ADMIN_CHAT_ID:
        logger.error("خطأ: ADMIN_CHAT_ID غير موجود!")
        # يمكن إرجاع Application وهمي أو إثارة خطأ هنا
        raise ValueError("ADMIN_CHAT_ID environment variable not set.")


    application = Application.builder().token(BOT_TOKEN).build()

    # توحيد معالجة زر العودة
    back_to_menu_handler = CallbackQueryHandler(back_to_menu, pattern='^back_to_menu$')
    text_message_filter = filters.TEXT & ~filters.COMMAND

    # معالج إجراءات الموافقة/الرفض للمشرف
    admin_action_handler = CallbackQueryHandler(handle_admin_action, pattern='^action\|(approve|reject)\|.+$')

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(new_request_handler, pattern='^new_request$')
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_choice, pattern='^(apology|leave|feedback|problem)$')
            ],
            # مسارات تتطلب الاسم والفريق أولاً (اعتذار وإجازة)
            FIRST_NAME: [back_to_menu_handler, MessageHandler(text_message_filter, first_name)],
            LAST_NAME: [back_to_menu_handler, MessageHandler(text_message_filter, last_name)],
            TEAM_NAME: [back_to_menu_handler, MessageHandler(text_message_filter, team_name)],

            # مسار الاعتذار
            APOLOGY_TYPE: [
                back_to_menu_handler,
                CallbackQueryHandler(apology_type, pattern='^(meeting|initiative|other)$')
            ],
            INITIATIVE_NAME: [back_to_menu_handler, MessageHandler(text_message_filter, initiative_name)],
            APOLOGY_REASON: [back_to_menu_handler, MessageHandler(text_message_filter, apology_reason)],
            APOLOGY_NOTES: [
                back_to_menu_handler,
                CallbackQueryHandler(apology_notes, pattern='^skip_apology_notes$'),
                MessageHandler(text_message_filter, apology_notes)
            ],

            # مسار الإجازة
            LEAVE_START_DATE: [back_to_menu_handler, MessageHandler(text_message_filter, leave_start_date)],
            LEAVE_END_DATE: [back_to_menu_handler, MessageHandler(text_message_filter, leave_end_date)],
            LEAVE_REASON: [back_to_menu_handler, MessageHandler(text_message_filter, leave_reason)],
            LEAVE_NOTES: [
                back_to_menu_handler,
                CallbackQueryHandler(leave_notes, pattern='^skip_leave_notes$'),
                MessageHandler(text_message_filter, leave_notes)
            ],

            # مسار المشاكل (مستقل)
            PROBLEM_DESCRIPTION: [back_to_menu_handler, MessageHandler(text_message_filter, problem_description)],
            PROBLEM_NOTES: [
                back_to_menu_handler,
                CallbackQueryHandler(problem_notes, pattern='^skip_problem_notes$'),
                MessageHandler(text_message_filter, problem_notes)
            ],

            # مسار الاقتراحات (مستقل)
            FEEDBACK_MESSAGE: [back_to_menu_handler, MessageHandler(text_message_filter, feedback_message)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(conv_handler)
    application.add_handler(admin_action_handler)
    
    return application

# يتم تعريف application_instance هنا ليتمكن Gunicorn من استدعائها
application_instance = main_setup()


def start_webhook() -> None:
    """تشغيل البوت باستخدام Webhooks على Render"""
    global application_instance
    
    if WEBHOOK_URL:
        logger.info("يتم التشغيل في بيئة Webhook...")
        # تعيين Webhook (إخبار تليجرام بعنوان URL الخاص بك)
        application_instance.run_webhook(
            listen="0.0.0.0",  # الاستماع على جميع الواجهات
            port=PORT,
            url_path=BOT_TOKEN,  # استخدام التوكن كمسار (path) سري
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
        logger.info(f"البوت بدأ العمل على Webhook URL: {WEBHOOK_URL}/{BOT_TOKEN}")
    else:
        logger.warning("لم يتم تعيين WEBHOOK_URL. يتم التشغيل بـ Polling (للتطوير المحلي فقط).")
        application_instance.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    # يتم استدعاء start_webhook مباشرة لتشغيل البوت في حال لم يكن Gunicorn يعمل
    # في بيئة Render، سيقوم Gunicorn باستدعاء application_instance مباشرة.
    start_webhook()
