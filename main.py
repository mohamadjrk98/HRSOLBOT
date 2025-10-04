import logging
import os
import time
import sqlite3 
import re
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

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_NAME = 'volunteers_system.db'

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Teams (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Volunteers (
            id INTEGER PRIMARY KEY,
            telegram_id INTEGER UNIQUE,
            full_name TEXT NOT NULL,
            team_id INTEGER,
            registration_date TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (team_id) REFERENCES Teams(id)
        )
    ''')

    initial_teams = [('فريق الدعم الأول',), ('فريق الدعم الثاني',), ('فريق المتابعة',)]
    for team in initial_teams:
        try:
            cursor.execute("INSERT INTO Teams (name) VALUES (?)", team)
        except sqlite3.IntegrityError:
            pass 

    conn.commit()
    conn.close()

def get_all_teams():
    conn = get_db_connection()
    teams = conn.execute("SELECT id, name FROM Teams").fetchall()
    conn.close()
    return teams

def add_new_volunteer_to_db(telegram_id, full_name, team_id):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO Volunteers (telegram_id, full_name, team_id) VALUES (?, ?, ?)",
            (telegram_id, full_name, team_id)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def is_admin(chat_id):
    if not ADMIN_CHAT_ID:
        return False
    return str(chat_id) == str(ADMIN_CHAT_ID)


(MAIN_MENU, FIRST_NAME, LAST_NAME, TEAM_NAME, 
 APOLOGY_TYPE, INITIATIVE_NAME, APOLOGY_REASON, APOLOGY_NOTES,
 LEAVE_START_DATE, LEAVE_END_DATE, LEAVE_REASON, LEAVE_NOTES,
 FEEDBACK_MESSAGE, PROBLEM_DESCRIPTION, PROBLEM_NOTES,
 ADMIN_MENU, ADD_VOLUNTEER_FULL_NAME, ADD_VOLUNTEER_SELECT_TEAM, ADD_VOLUNTEER_FINALIZE, ADD_VOLUNTEER_TELEGRAM_ID) = range(20)

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')

WEBHOOK_URL = os.getenv('WEBHOOK_URL') 
PORT = int(os.environ.get('PORT', '5000')) 

def generate_request_id():
    return f"REQ{int(time.time())}"

def get_request_title(request_type):
    titles = {
        'apology': 'طلب الاعتذار',
        'leave': 'طلب الإجازة',
        'problem': 'بلاغ المشكلة',
        'feedback': 'الاقتراح/الملاحظة'
    }
    return titles.get(request_type, 'طلب')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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

    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة المشرف", callback_data='admin_menu')])
        
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

async def admin_menu_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ غير مصرح لك بالدخول إلى هذه القائمة.")
        return MAIN_MENU
    
    return await admin_menu_display(update, context)


async def admin_menu_display(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    if query and not is_admin(query.from_user.id):
        await query.edit_message_text("❌ غير مصرح لك بالدخول إلى هذه القائمة.")
        return MAIN_MENU

    keyboard = [
        [InlineKeyboardButton("➕ إضافة متطوع جديد", callback_data='add_volunteer')],
        [InlineKeyboardButton("📜 عرض المتطوعين (قريباً)", callback_data='view_volunteers')],
        [InlineKeyboardButton("🔙 عودة للقائمة الرئيسية", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        "⚙️ **لوحة المشرف**\n\n"
        "ما هي الإجراء الذي ترغب في تنفيذه؟"
    )

    if query:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        
    return ADMIN_MENU

async def admin_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    choice = query.data
    
    if choice == 'add_volunteer':
        context.user_data.clear() 
        
        keyboard = [[InlineKeyboardButton("🔙 عودة لقائمة المشرف", callback_data='admin_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "➕ **إضافة متطوع جديد**\n\n"
            "الرجاء إدخال **الاسم الكامل** للمتطوع (الاسم الأول واسم العائلة):",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return ADD_VOLUNTEER_FULL_NAME
    
    elif choice == 'view_volunteers':
        await query.edit_message_text("هذه الميزة قيد التطوير. عودة للقائمة الرئيسية.", 
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]))
        return MAIN_MENU
        
    return ADMIN_MENU

async def add_volunteer_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_volunteer_full_name'] = update.message.text
    
    keyboard = [[InlineKeyboardButton("🔙 عودة لقائمة المشرف", callback_data='admin_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"تم حفظ الاسم: **{update.message.text}**\n\n"
        "الرجاء إدخال **رقم تعريف تيليجرام (Telegram ID)** للمتطوع (يكون رقمًا):",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return ADD_VOLUNTEER_TELEGRAM_ID

async def add_volunteer_telegram_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id_str = update.message.text.strip()
    
    if not telegram_id_str.isdigit():
        await update.message.reply_text(
            "⚠️ الرجاء إدخال رقم تعريف تيليجرام **صحيح** (رقم فقط).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data='admin_menu')]])
        )
        return ADD_VOLUNTEER_TELEGRAM_ID 

    context.user_data['new_volunteer_telegram_id'] = int(telegram_id_str)
    
    teams = get_all_teams()
    keyboard = []
    
    for team in teams:
        callback_data = f"team_select|{team['id']}|{team['name']}"
        keyboard.append([InlineKeyboardButton(team['name'], callback_data=callback_data)])
        
    keyboard.append([InlineKeyboardButton("🔙 عودة لقائمة المشرف", callback_data='admin_menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"تم حفظ رقم المعرف: **{telegram_id_str}**\n\n"
        "الرجاء اختيار الفريق الذي سينتمي إليه المتطوع:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return ADD_VOLUNTEER_SELECT_TEAM

async def add_volunteer_select_team(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data_parts = query.data.split('|')
    team_id = int(data_parts[1])
    team_name = data_parts[2]
    
    full_name = context.user_data.get('new_volunteer_full_name')
    telegram_id = context.user_data.get('new_volunteer_telegram_id')

    success = add_new_volunteer_to_db(telegram_id, full_name, team_id)
    
    if success:
        message = (
            f"✅ **تمت الإضافة بنجاح!**\n\n"
            f"👤 الاسم: {full_name}\n"
            f"🆔 ID: `{telegram_id}`\n"
            f"👥 الفريق: {team_name}\n\n"
            "يمكن للمتطوع الآن استخدام البوت."
        )
    else:
        message = (
            f"❌ **فشل الإضافة!**\n\n"
            "قد يكون المتطوع (برقم ID: "
            f"`{telegram_id}`) مسجلاً مسبقاً في النظام. "
            "الرجاء التأكد من رقم الـ ID والمحاولة مرة أخرى."
        )

    context.user_data.clear()
    
    keyboard = [[InlineKeyboardButton("🔙 عودة لقائمة المشرف", callback_data='admin_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    return ADMIN_MENU

async def main_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    choice = query.data
    context.user_data.clear() 
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

    await query.edit_message_text(
        'الرجاء إدخال اسمك الأول:',
        reply_markup=reply_markup
    )
    return FIRST_NAME

async def first_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    
async def apology_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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

    if type_choice == 'initiative':
        await query.edit_message_text(
            'الرجاء إدخال **اسم المبادرة** التي تعتذر عنها:',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return INITIATIVE_NAME
    else:
        await query.edit_message_text(
            f'تم اختيار: {context.user_data["apology_type"]}\n\n'
            'الرجاء كتابة سبب الاعتذار بالتفصيل:',
            reply_markup=reply_markup
        )
        return APOLOGY_REASON

async def initiative_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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

    if update.callback_query:
        await message.edit_text(volunteer_message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await message.reply_text(volunteer_message, reply_markup=reply_markup, parse_mode='Markdown')

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


async def leave_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        f'• تاريخ البدء: {leave_start_date}\n'
        f'• تاريخ الانتهاء: {leave_end_date}\n'
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
        f'• تاريخ بدء الإجازة: {leave_start_date}\n'
        f'• تاريخ انتهاء الإجازة: {leave_end_date}\n'
        f'• سبب الإجازة: {leave_reason}\n'
        f'• ملاحظات: {leave_notes}\n'
        f'━━━━━━━━━━━━━━━━━'
    )

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

    if update.callback_query:
        await message.edit_text(volunteer_message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await message.reply_text(volunteer_message, reply_markup=reply_markup, parse_mode='Markdown')

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

async def problem_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['problem_description'] = update.message.text

    keyboard = [
        [InlineKeyboardButton("⏭️ تخطي", callback_data='skip_problem_notes')],
        [InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        'هل لديك أي ملاحظات إضافية بخصوص المشكلة؟\n'
        '(اكتب ملاحظاتك أو اضغط تخطي)',
        reply_markup=reply_markup
    )
    return PROBLEM_NOTES


async def problem_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        f'🔖 رقم الطلب: `{request_id}`\n\n'
        f'📋 **ملخص البلاغ:**\n'
        f'• الوصف: {problem_description}\n'
        f'• ملاحظات: {problem_notes}\n\n'
        f'سيتم النظر في المشكلة وإبلاغك بالتحديثات.'
    )

    admin_message = (
        f'🔧 **بلاغ مشكلة جديد**\n'
        f'━━━━━━━━━━━━━━━━━\n'
        f'🔖 رقم الطلب: `{request_id}`\n'
        f'👤 المبلغ: {user.first_name} {user.last_name or ""}\n'
        f'🆔 المعرف: @{user.username or "لا يوجد"}\n'
        f'🆔 رقم المستخدم: {user.id}\n\n'
        f'📋 **التفاصيل:**\n'
        f'• وصف المشكلة: {problem_description}\n'
        f'• ملاحظات: {problem_notes}\n'
        f'━━━━━━━━━━━━━━━━━'
    )
    
    admin_keyboard = [
        [
            InlineKeyboardButton("✅ تم الحل", callback_data=f'action|approve|{request_type}|{request_id}|{user_id}'),
            InlineKeyboardButton("❌ غير منطبقة", callback_data=f'action|reject|{request_type}|{request_id}|{user_id}')
        ]
    ]
    admin_reply_markup = InlineKeyboardMarkup(admin_keyboard)

    keyboard = [
        [InlineKeyboardButton("📝 طلب جديد", callback_data='new_request')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await message.edit_text(volunteer_message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await message.reply_text(volunteer_message, reply_markup=reply_markup, parse_mode='Markdown')

    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_message,
            reply_markup=admin_reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"خطأ في إرسال الرسالة للمدير (المشكلة): {e}")

    context.user_data.clear()
    return ConversationHandler.END
    
async def feedback_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['feedback_message'] = update.message.text

    user = update.effective_user
    request_id = context.user_data.get('request_id', 'N/A')
    request_type = context.user_data.get('request_type', 'feedback')
    feedback_text = update.message.text
    
    volunteer_message = (
        f'✅ **تم استلام اقتراحك/ملاحظتك!**\n\n'
        f'🔖 رقم الطلب: `{request_id}`\n\n'
        f'**شكراً لك على مساهمتك القيمة 💚**\n\n'
        f'تم إرسال الاقتراح للمراجعة.'
    )

    admin_message = (
        f'💡 **اقتراح/ملاحظة جديدة**\n'
        f'━━━━━━━━━━━━━━━━━\n'
        f'🔖 رقم الطلب: `{request_id}`\n'
        f'👤 المرسل: {user.first_name} {user.last_name or ""}\n'
        f'🆔 المعرف: @{user.username or "لا يوجد"}\n'
        f'🆔 رقم المستخدم: {user.id}\n\n'
        f'📋 **التفاصيل:**\n'
        f'• الاقتراح: {feedback_text}\n'
        f'━━━━━━━━━━━━━━━━━'
    )

    keyboard = [
        [InlineKeyboardButton("📝 طلب جديد", callback_data='new_request')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(volunteer_message, reply_markup=reply_markup, parse_mode='Markdown')

    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_message,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"خطأ في إرسال الرسالة للمدير (الاقتراح): {e}")

    context.user_data.clear()
    return ConversationHandler.END

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == 'back_to_menu' or data == 'new_request':
        if context.user_data:
             context.user_data.clear()
        return await start(update, context) 

    elif data == 'admin_menu':
        return await admin_menu_display(update, context) 

    elif data == 'add_volunteer':
        return await admin_menu_choice(update, context) 

    elif data.startswith('action|'):
        parts = data.split('|')
        action, request_type, request_id, user_id = parts[1], parts[2], parts[3], parts[4]
        
        if is_admin(query.from_user.id):
            user_message = f"تم **{'قبول' if action == 'approve' else 'رفض'}** {get_request_title(request_type)} الخاص بك: `{request_id}`."
            
            try:
                await context.bot.send_message(chat_id=user_id, text=user_message, parse_mode='Markdown')
                
                await query.edit_message_text(
                    query.message.text + 
                    f'\n\n✅ **تم الرد من قبل {query.from_user.first_name}: {action.upper()}**',
                    reply_markup=None,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"خطأ في إرسال الرد للمستخدم {user_id}: {e}")
                await query.edit_message_text(f"❌ تم اتخاذ الإجراء، لكن حدث خطأ في إرسال الرد للمستخدم: {e}", reply_markup=None)
        else:
            await query.answer("❌ غير مصرح لك باتخاذ هذا الإجراء.")
            
        return MAIN_MENU 

    if data in ['apology', 'leave', 'problem', 'feedback']:
        return await main_menu_choice(update, context)

    if data.startswith('skip_'):
        pass
        
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    logger.info("المستخدم %s ألغى المحادثة.", user.first_name)
    
    keyboard = [
        [InlineKeyboardButton("📝 طلب اعتذار", callback_data='apology')],
        [InlineKeyboardButton("🏖️ طلب إجازة", callback_data='leave')],
        [InlineKeyboardButton("🔧 قسم حل المشاكل", callback_data='problem')],
        [InlineKeyboardButton("💡 اقتراحات وملاحظات", callback_data='feedback')]
    ]

    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة المشرف", callback_data='admin_menu')])
        
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        'تم إلغاء الطلب. يمكنك البدء بطلب جديد.', 
        reply_markup=reply_markup
    )
    context.user_data.clear()
    return ConversationHandler.END

def main() -> None:
    setup_database()
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN غير متوفر. يرجى التأكد من تعيين متغير البيئة.")
        return

    application = Application.builder().token(BOT_TOKEN).build()
    
    # فلتر بسيط وموثوق للنصوص التي ليست أوامر
    TEXT_MESSAGE_FILTER = filters.TEXT & ~filters.COMMAND 
    
    main_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start), CommandHandler("admin", admin_menu_start, filters=filters.Chat(chat_id=ADMIN_CHAT_ID))],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(handle_callback_query, pattern='^apology$|^leave$|^problem$|^feedback$|^admin_menu$')
            ],
            
            # تم التعديل لاستخدام TEXT_MESSAGE_FILTER لضمان التقاط الرسالة
            FIRST_NAME: [MessageHandler(TEXT_MESSAGE_FILTER, first_name)],
            LAST_NAME: [MessageHandler(TEXT_MESSAGE_FILTER, last_name)],
            TEAM_NAME: [MessageHandler(TEXT_MESSAGE_FILTER, team_name)],
            
            APOLOGY_TYPE: [CallbackQueryHandler(apology_type, pattern='^meeting$|^initiative$|^other$')],
            INITIATIVE_NAME: [MessageHandler(TEXT_MESSAGE_FILTER, initiative_name)],
            APOLOGY_REASON: [MessageHandler(TEXT_MESSAGE_FILTER, apology_reason)],
            APOLOGY_NOTES: [
                MessageHandler(TEXT_MESSAGE_FILTER, apology_notes),
                CallbackQueryHandler(apology_notes, pattern='^skip_apology_notes$')
            ],

            LEAVE_START_DATE: [MessageHandler(TEXT_MESSAGE_FILTER, leave_start_date)],
            LEAVE_END_DATE: [MessageHandler(TEXT_MESSAGE_FILTER, leave_end_date)],
            LEAVE_REASON: [MessageHandler(TEXT_MESSAGE_FILTER, leave_reason)],
            LEAVE_NOTES: [
                MessageHandler(TEXT_MESSAGE_FILTER, leave_notes),
                CallbackQueryHandler(leave_notes, pattern='^skip_leave_notes$')
            ],

            PROBLEM_DESCRIPTION: [MessageHandler(TEXT_MESSAGE_FILTER, problem_description)],
            PROBLEM_NOTES: [
                MessageHandler(TEXT_MESSAGE_FILTER, problem_notes),
                CallbackQueryHandler(problem_notes, pattern='^skip_problem_notes$')
            ],

            FEEDBACK_MESSAGE: [MessageHandler(TEXT_MESSAGE_FILTER, feedback_message)],
            
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_choice, pattern='^add_volunteer$|^view_volunteers$')
            ],
            
            ADD_VOLUNTEER_FULL_NAME: [MessageHandler(TEXT_MESSAGE_FILTER, add_volunteer_full_name)],
            ADD_VOLUNTEER_TELEGRAM_ID: [MessageHandler(TEXT_MESSAGE_FILTER, add_volunteer_telegram_id)],
            ADD_VOLUNTEER_SELECT_TEAM: [CallbackQueryHandler(add_volunteer_select_team, pattern='^' + re.escape('team_select|'))]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(handle_callback_query, pattern='^back_to_menu$'),
            CallbackQueryHandler(handle_callback_query, pattern='^admin_menu$')
        ]
    )
    
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    application.add_handler(main_conv)

    if WEBHOOK_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f'{WEBHOOK_URL}/{BOT_TOKEN}'
        )
        logger.info(f"البوت يعمل عبر Webhook على البورت {PORT}")
    else:
        logger.info("البوت يعمل عبر Polling")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
