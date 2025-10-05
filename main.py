import os
import time
import sqlite3 
import random
import requests
import json
import logging
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

# --------------------------------- إعدادات التسجيل (Logging) ---------------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --------------------------------- تعريف الحالات والثوابت ---------------------------------

# الحالات (States) المستخدمة في ConversationHandler
(MAIN_MENU, FIRST_NAME, LAST_NAME, TEAM_NAME, 
 APOLOGY_TYPE, INITIATIVE_NAME, APOLOGY_REASON, APOLOGY_NOTES,
 LEAVE_START_DATE, LEAVE_END_DATE, LEAVE_REASON, LEAVE_NOTES,
 FEEDBACK_MESSAGE, PROBLEM_DESCRIPTION, PROBLEM_NOTES,
 ADMIN_MENU, ADD_VOLUNTEER_FULL_NAME, ADD_VOLUNTEER_SELECT_TEAM, ADD_VOLUNTEER_FINALIZE,
 REFERENCES_MENU) = range(20) 

# متغيرات البيئة (Environment Variables)
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID') # يُستخدم لإرسال الطلبات إليه
HR_CONTACT_INFO = os.getenv('HR_CONTACT_INFO', 'مسؤول الموارد البشرية') # رقم أو معرف HR

# متغيرات خاصة بـ Webhook Render
WEBHOOK_URL = os.getenv('WEBHOOK_URL') 
PORT = int(os.environ.get('PORT', '5000')) 

# --------------------------------- إعداد قاعدة البيانات ---------------------------------

DB_NAME = 'volunteers_system.db'

def get_db_connection():
    """إنشاء اتصال بقاعدة بيانات SQLite"""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    """إنشاء الجداول اللازمة وتعبئة البيانات الأولية"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Teams Table (الفرق)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Teams (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
    ''')
    
    # 2. Volunteers Table (المتطوعون)
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
    
    # 3. Request Counter Table (لمتابعة الترقيم المتسلسل)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS RequestCounter (
            id INTEGER PRIMARY KEY,
            count INTEGER NOT NULL
        )
    ''')
    # تهيئة العداد إذا كان الجدول فارغًا
    if cursor.execute("SELECT COUNT(*) FROM RequestCounter").fetchone()[0] == 0:
        cursor.execute("INSERT INTO RequestCounter (id, count) VALUES (1, 0)")


    # إضافة فرق مبدئية إذا لم تكن موجودة
    initial_teams = [('فريق الدعم الأول',), ('فريق الدعم الثاني',), ('فريق المتابعة',)]
    for team in initial_teams:
        try:
            cursor.execute("INSERT INTO Teams (name) VALUES (?)", team)
        except sqlite3.IntegrityError:
            pass 

    conn.commit()
    conn.close()

def get_all_teams():
    """جلب جميع الفرق من قاعدة البيانات"""
    conn = get_db_connection()
    teams = conn.execute("SELECT id, name FROM Teams").fetchall()
    conn.close()
    return teams

def add_new_volunteer_to_db(telegram_id, full_name, team_id):
    """إدراج متطوع جديد في جدول المتطوعين"""
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
    """التحقق مما إذا كان المستخدم هو المشرف"""
    if not ADMIN_CHAT_ID:
        return False
    return str(chat_id) == str(ADMIN_CHAT_ID)


def generate_request_id():
    """توليد رقم طلب متسلسل يبدأ من 0001"""
    conn = get_db_connection()
    try:
        # زيادة العداد والحصول على القيمة الجديدة
        cursor = conn.cursor()
        cursor.execute("UPDATE RequestCounter SET count = count + 1 WHERE id = 1")
        conn.commit()
        
        new_count = conn.execute("SELECT count FROM RequestCounter WHERE id = 1").fetchone()[0]
        conn.close()
        # تنسيق الرقم ليكون أربعة خانات (مثال: 0001, 0010)
        return f"REQ{new_count:04d}"
    except Exception as e:
        logger.error(f"خطأ في توليد رقم الطلب: {e}")
        conn.close()
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

# --------------------------------- العبارات التحفيزية ---------------------------------

MOTIVATIONAL_QUOTES = [
    "‏الخير الذي تفعله لا يضيع أبدًا، ستجده في صحيفتك أثراً جميلاً لا يُمحى. ✨",
    "في كل عمل تطوعي، أنت لا تقدم المساعدة للآخرين وحسب، بل تزرع الأمل في قلبك أيضاً. 💚",
    "تذكر دائماً أن أصغر جهد تبذله في مساعدة الآخرين، هو أعظم أثر في ميزان الأجر. 🌟",
    "التفاؤل ليس مجرد كلمة، بل هو فعل إيجابي يبدأ منك. استمر في نشر الضوء. 💡",
    "العمل الخيري لا يتطلب مالاً دائماً، يكفي أن تقدم جزءاً من روحك ووقتك. شكراً لجهدك. 🙏",
    "كن أنت التغيير الذي تتمنى أن تراه في العالم. كل خطوة تطوعية هي بداية. 🌍",
    "المتطوعون هم القلب النابض لأي مجتمع، بجهودكم تتسع دائرة العطاء. ❤️",
    "الأمل شجرة لا يثمر إلا بالعمل. استمر في السقاية! 🌳",
    "أثرك الجميل يُرى في عيون من ساعدتهم. لا تستخف بأي عمل قمت به. 🌷",
    "إذا أردت أن تكون سعيداً، فكن سبباً في سعادة غيرك. هذا هو جوهر التطوع. 😊",
    "رحلة الألف ميل تبدأ بخطوة، وأثمن الخطوات هي تلك التي تخطوها لخدمة الآخرين. 🚶",
    "أنت لست مجرد متطوع، أنت صانع فرق في حياة الكثيرين. دمت مبدعاً. 🦸",
    "اليأس لا يليق بمن عرفوا معنى العطاء والخير. المستقبل ينتظر من يزرع فيه الأمل. 🌱",
    "جبر الخواطر هو فن لا يتقنه إلا الأنقياء، شكراً لقلبك الطيب. 💎",
    "اجعلوا أثركم كالمطر، يسقي الأرض ويحييها دون ضجيج. العمل الصامت أبلغ. 🌧️",
    "قد لا تذكر كم مرة سقطت، لكنك ستذكر كم مرة مدت يدك للمساعدة. 💪",
    "تذكر: كل متطوع هو بطل حقيقي في الحياة اليومية. استمر في إنقاذ العالم بطريقتك. 🛡️",
    "لا يوجد عمل صغير عندما يقدم من قلب كبير. عطاؤك لا يُقدر بثمن. 🎁",
    "التطوع هو أن تترك مكاناً أفضل مما وجدته عليه. شكراً لترك بصمتك الرائعة. ✍️",
    "حافظ على إشراقتك، فالعالم بحاجة إلى متفائلين مثلك ليضيئوا دروبهم. ☀️",
    "إن أفضل طريقة لتجد نفسك، هي أن تضيعها في خدمة الآخرين. (غاندي) 🕊️",
    "لا تتوقف عن الحلم، والأهم: لا تتوقف عن العمل لتحويل هذه الأحلام إلى واقع ملموس للجميع. 🚀"
]

# --------------------------------- دوال المساعدة للرسائل ---------------------------------

async def delete_previous_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """يحاول حذف رسالة البوت الأخيرة المخزنة في context.user_data."""
    message_id = context.user_data.pop('last_bot_message_id', None)
    if message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            logger.debug(f"فشل في حذف الرسالة {message_id}: {e}")

async def send_and_track_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup: InlineKeyboardMarkup = None, parse_mode: str = None):
    """يرسل رسالة جديدة ويخزن رقمها لتنظيف المحادثة لاحقاً."""
    message = await update.effective_chat.send_message(
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode
    )
    context.user_data['last_bot_message_id'] = message.message_id
    return message


# --------------------------------- الدوال الأساسية ---------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """البداية - عرض القائمة الرئيسية (تم التعديل لتحرير الرسالة)"""
    query = update.callback_query
    
    if query:
        await query.answer()
        user = query.from_user
        message = query.message
        # لا نحذف هنا لأننا سنقوم بتحرير الرسالة
    else:
        user = update.effective_user
        message = update.message
        # محاولة حذف رسالة الأمر /start إذا لم تكن أول رسالة
        if message.text and message.text.startswith('/start'):
             try:
                 await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
             except Exception:
                 pass # لا يهم إذا فشل الحذف

    # تنظيف بيانات المستخدم ما عدا بيانات المشرف
    for key in list(context.user_data.keys()):
        if key not in ['admin_mode']:
            del context.user_data[key]

    keyboard = [
        [InlineKeyboardButton("📝 طلب اعتذار", callback_data='apology'),
         InlineKeyboardButton("🏖️ طلب إجازة", callback_data='leave')],
        [InlineKeyboardButton("🔧 قسم المشاكل", callback_data='problem'),
         InlineKeyboardButton("💡 اقتراحات وملاحظات", callback_data='feedback')],
        [InlineKeyboardButton("📚 مراجع الفريق", callback_data='references_menu'),
         InlineKeyboardButton("🎁 هدية لطيفة", callback_data='motivational_gift')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f'أهلاً {user.first_name}! 👋\n\n'
        'أنا بوت طلبات المتطوعين.\n'
        'كيف يمكنني مساعدتك اليوم؟\n\n'
        'لإلغاء الطلب في أي وقت، أرسل /cancel'
    )

    if query and query.message.text:
        try:
            message = await query.edit_message_text(text, reply_markup=reply_markup)
            context.user_data['last_bot_message_id'] = message.message_id
        except Exception:
             # إذا فشل التحرير (مثل محاولة تحرير رسالة قديمة جداً)، نرسل رسالة جديدة
             await context.bot.send_message(
                chat_id=message.chat_id, 
                text=text, 
                reply_markup=reply_markup,
                reply_to_message_id=None
            )
    else:
        message = await update.message.reply_text(text, reply_markup=reply_markup, reply_to_message_id=None)
        context.user_data['last_bot_message_id'] = message.message_id


    return MAIN_MENU

# --------------------------------- دوال الأزرار الجديدة ---------------------------------

async def references_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """عرض قائمة المراجع"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        # **تحديث هذه الروابط**
        [InlineKeyboardButton("📄 مدونة السلوك", url="YOUR_CODE_OF_CONDUCT_LINK_HERE")],
        [InlineKeyboardButton("📜 القرارات الخاصة بالفريق", url="YOUR_TEAM_DECISIONS_LINK_HERE")],
        [InlineKeyboardButton("⚙️ تعليمات المركز", url="YOUR_CENTER_INSTRUCTIONS_LINK_HERE")],
        [InlineKeyboardButton("🎙️ جلسات المركز", url="YOUR_CENTER_SESSIONS_LINK_HERE")],
        [InlineKeyboardButton("🔙 عودة للقائمة الرئيسية", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        "📚 **مراجع الفريق**\n\n"
        "يمكنك الوصول إلى المستندات والروابط الهامة الخاصة بالعمل التطوعي والمركز من القائمة أدناه:"
    )

    await query.edit_message_text(
        text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return REFERENCES_MENU 

async def send_motivational_gift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """اختيار وإرسال عبارة تحفيزية عشوائية"""
    query = update.callback_query
    await query.answer()
    
    quote = random.choice(MOTIVATIONAL_QUOTES)
    
    gift_message = (
        "🎁 **هدية لطيفة لك!** 🎁\n"
        "━━━━━━━\n"
        f"*{quote}*\n"
        "━━━━━━━\n"
        "شكراً لجهودك وعطائك المتواصل. أنت تصنع فرقاً حقيقياً! 🌟"
    )

    await query.message.reply_text(
        gift_message, 
        parse_mode='Markdown'
    )
    
    # العودة إلى القائمة الرئيسية (بدون إرسال رسالة تكرار)
    return await start(update, context)

# --------------------------------- دوال القوائم والمسارات ---------------------------------

async def main_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة اختيار القائمة الرئيسية"""
    query = update.callback_query
    choice = query.data
    
    if choice == 'motivational_gift':
        return await send_motivational_gift(update, context)
    elif choice == 'references_menu':
        return await references_menu(update, context)
        
    await query.answer()

    # تنظيف البيانات قبل بدء طلب جديد
    context.user_data.clear() 
    context.user_data['request_type'] = choice
    context.user_data['request_id'] = generate_request_id() # توليد رقم الطلب هنا

    keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if choice == 'feedback':
        message = await query.edit_message_text(
            '💡 اقتراحات وملاحظات\n\n'
            'الرجاء كتابة اقتراحك أو ملاحظتك:',
            reply_markup=reply_markup
        )
        context.user_data['last_bot_message_id'] = message.message_id
        return FEEDBACK_MESSAGE

    elif choice == 'problem':
        message = await query.edit_message_text(
            '🔧 قسم حل المشاكل\n\n'
            'الرجاء وصف المشكلة التي تواجهها بوضوح:',
            reply_markup=reply_markup
        )
        context.user_data['last_bot_message_id'] = message.message_id
        return PROBLEM_DESCRIPTION

    # طلبات تحتاج اسم (apology, leave)
    message = await query.edit_message_text(
        'الرجاء إدخال اسمك الأول:',
        reply_markup=reply_markup
    )
    context.user_data['last_bot_message_id'] = message.message_id
    return FIRST_NAME

async def first_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ الاسم الأول وطلب الكنية مع تنظيف الرسائل"""
    await delete_previous_message(context, update.effective_chat.id)
    context.user_data['first_name'] = update.message.text

    keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await send_and_track_message(
        update, 
        context,
        f'أهلاً {update.message.text}!\n\n'
        'الرجاء إدخال الكنية (اسم العائلة):',
        reply_markup=reply_markup
    )
    return LAST_NAME


async def last_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ الكنية وطلب اسم الفريق مع تنظيف الرسائل"""
    await delete_previous_message(context, update.effective_chat.id)
    context.user_data['last_name'] = update.message.text

    keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await send_and_track_message(
        update, 
        context,
        'ما هو الفريق الذي تنتمي إليه؟\n'
        '(مثال: فريق الدعم الأول، الدعم الثاني، الخ)',
        reply_markup=reply_markup
    )
    return TEAM_NAME


async def team_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ اسم الفريق والانتقال حسب نوع الطلب مع تنظيف الرسائل"""
    await delete_previous_message(context, update.effective_chat.id)
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

        await send_and_track_message(
            update, 
            context,
            '📝 طلب اعتذار\n\n'
            'ما هو نوع الفعالية/الاعتذار؟',
            reply_markup=reply_markup
        )
        return APOLOGY_TYPE

    elif request_type == 'leave':
        keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await send_and_track_message(
            update, 
            context,
            '🏖️ طلب إجازة\n\n'
            '📌 **ملاحظة هامة:** مدة الإجازة المسموحة للمتطوع خلال السنة هي **شهر واحد فقط** للامتحانات و**الظروف القاهرة**.\n\n'
            'الرجاء إدخال **تاريخ بدء الإجازة**:\n'
            '(يُرجى استخدام صيغة واضحة مثل: 2025-11-01)',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return LEAVE_START_DATE

    return MAIN_MENU

# --------------------------------- دوال مسار الاعتذار (APOLOGY) ---------------------------------

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

    if type_choice == 'initiative':
        message = await query.edit_message_text(
            'الرجاء إدخال **اسم المبادرة** التي تعتذر عنها:',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        context.user_data['last_bot_message_id'] = message.message_id
        return INITIATIVE_NAME
    else:
        message = await query.edit_message_text(
            f'تم اختيار: {context.user_data["apology_type"]}\n\n'
            'الرجاء كتابة سبب الاعتذار بالتفصيل:',
            reply_markup=reply_markup
        )
        context.user_data['last_bot_message_id'] = message.message_id
        return APOLOGY_REASON

async def initiative_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ اسم المبادرة وطلب سبب الاعتذار مع تنظيف الرسائل"""
    await delete_previous_message(context, update.effective_chat.id)
    context.user_data['initiative_name'] = update.message.text

    keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await send_and_track_message(
        update,
        context,
        f'المبادرة: {update.message.text}\n\n'
        'الرجاء كتابة سبب الاعتذار بالتفصيل:',
        reply_markup=reply_markup
    )
    return APOLOGY_REASON


async def apology_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ سبب الاعتذار وطلب الملاحظات مع تنظيف الرسائل"""
    await delete_previous_message(context, update.effective_chat.id)
    context.user_data['apology_reason'] = update.message.text

    keyboard = [
        [InlineKeyboardButton("⏭️ تخطي", callback_data='skip_apology_notes')],
        [InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await send_and_track_message(
        update,
        context,
        'هل لديك أي ملاحظات إضافية بخصوص الاعتذار؟\n'
        '(اكتب ملاحظاتك أو اضغط تخطي)',
        reply_markup=reply_markup
    )
    return APOLOGY_NOTES


async def apology_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ الملاحظات وإرسال الطلب للمدير"""
    # لا حاجة لحذف الرسائل هنا، سنقوم بالتحرير أو إرسال رسالة جديدة
    message = update.message
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        context.user_data['apology_notes'] = 'لا توجد'
        message = query.message
    else:
        await delete_previous_message(context, update.effective_chat.id)
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
    apology_notes_val = context.user_data.get('apology_notes', 'لا توجد')

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
        f'• ملاحظات: {apology_notes_val}\n\n'
        f'**أثرك موجود دائماً.. شكراً لأنك معنا 💚**\n\n'
        f'سيتم مراجعة طلبك قريباً. **إذا تأخر الرد لأكثر من ساعة، يرجى مراسلة {HR_CONTACT_INFO} للمتابعة الفورية.**'
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
        f'• ملاحظات: {apology_notes_val}\n'
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


# --------------------------------- دوال مسار الإجازة (LEAVE) ---------------------------------

async def leave_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ تاريخ بدء الإجازة وطلب تاريخ الانتهاء مع تنظيف الرسائل"""
    await delete_previous_message(context, update.effective_chat.id)
    context.user_data['leave_start_date'] = update.message.text

    keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await send_and_track_message(
        update, 
        context,
        f'تاريخ البدء: {update.message.text}\n\n'
        'الرجاء إدخال **تاريخ انتهاء الإجازة**:',
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return LEAVE_END_DATE

async def leave_end_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ تاريخ انتهاء الإجازة وطلب السبب مع تنظيف الرسائل"""
    await delete_previous_message(context, update.effective_chat.id)
    context.user_data['leave_end_date'] = update.message.text

    keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await send_and_track_message(
        update, 
        context,
        f'تاريخ الانتهاء: {update.message.text}\n\n'
        'الرجاء كتابة سبب طلب الإجازة بوضوح:',
        reply_markup=reply_markup
    )
    return LEAVE_REASON


async def leave_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ سبب الإجازة وطلب الملاحظات مع تنظيف الرسائل"""
    await delete_previous_message(context, update.effective_chat.id)
    context.user_data['leave_reason'] = update.message.text

    keyboard = [
        [InlineKeyboardButton("⏭️ تخطي", callback_data='skip_leave_notes')],
        [InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await send_and_track_message(
        update,
        context,
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
        await delete_previous_message(context, update.effective_chat.id)
        context.user_data['leave_notes'] = update.message.text

    user = update.effective_user
    request_id = context.user_data.get('request_id', 'N/A')
    user_id = user.id
    request_type = context.user_data.get('request_type', 'leave')
    first_name = context.user_data.get('first_name', 'غير محدد')
    last_name = context.user_data.get('last_name', 'غير محدد')
    team_name = context.user_data.get('team_name', 'غير محدد')
    leave_start_date_val = context.user_data.get('leave_start_date', 'غير محدد')
    leave_end_date_val = context.user_data.get('leave_end_date', 'غير محدد')
    leave_reason_val = context.user_data.get('leave_reason', 'غير محدد')
    leave_notes_val = context.user_data.get('leave_notes', 'لا توجد')

    volunteer_message = (
        f'✅ **تم استلام طلب الإجازة!**\n\n'
        f'🔖 رقم الطلب: `{request_id}`\n\n'
        f'📋 **ملخص الطلب:**\n'
        f'• الاسم: {first_name} {last_name}\n'
        f'• الفريق: {team_name}\n'
        f'• تاريخ البدء: {leave_start_date_val}\n'
        f'• تاريخ الانتهاء: {leave_end_date_val}\n'
        f'• السبب: {leave_reason_val}\n'
        f'• ملاحظات: {leave_notes_val}\n\n'
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
        f'• تاريخ بدء الإجازة: {leave_start_date_val}\n'
        f'• تاريخ انتهاء الإجازة: {leave_end_date_val}\n'
        f'• سبب الإجازة: {leave_reason_val}\n'
        f'• ملاحظات: {leave_notes_val}\n'
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

# --------------------------------- دوال مسار المشاكل والاقتراحات ---------------------------------

async def problem_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ وصف المشكلة وطلب الملاحظات مع تنظيف الرسائل"""
    await delete_previous_message(context, update.effective_chat.id)
    context.user_data['problem_description'] = update.message.text

    keyboard = [
        [InlineKeyboardButton("⏭️ تخطي", callback_data='skip_problem_notes')],
        [InlineKeyboardButton("🔙 عودة", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await send_and_track_message(
        update,
        context,
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
        await delete_previous_message(context, update.effective_chat.id)
        context.user_data['problem_notes'] = update.message.text

    user = update.effective_user
    request_id = context.user_data.get('request_id', 'N/A')
    user_id = user.id
    request_type = context.user_data.get('request_type', 'problem')
    problem_description = context.user_data.get('problem_description', 'غير محدد')
    problem_notes_val = context.user_data.get('problem_notes', 'لا توجد')

    volunteer_message = (
        f'✅ **تم استلام بلاغ المشكلة!**\n\n'
        f'🔖 رقم البلاغ: `{request_id}`\n\n'
        f'📋 **ملخص البلاغ:**\n'
        f'• المشكلة: {problem_description}\n'
        f'• ملاحظات: {problem_notes_val}\n\n'
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
        f'• ملاحظات: {problem_notes_val}\n'
        f'━━━━━━━━━━━━━━━━━'
    )

    admin_keyboard = [
        [
            InlineKeyboardButton("✅ تم الحل", callback_data=f'action|approve|{request_type}|{request_id}|{user_id}'),
            InlineKeyboardButton("❌ يتطلب متابعة", callback_data=f'action|reject|{request_type}|{request_id}|{user_id}')
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


async def feedback_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """استلام الاقتراح وإرساله للمدير"""
    await delete_previous_message(context, update.effective_chat.id)
    
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


# --------------------------------- دوال المشرف لإضافة متطوع ---------------------------------

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """نقطة دخول المشرف (الأمر /admin)"""
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("❌ غير مصرح لك باستخدام هذا الأمر.")
        return ConversationHandler.END
    
    # محاولة حذف رسالة الأمر /admin
    if update.message:
        try:
             await context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
        except Exception:
            pass # لا يهم إذا فشل الحذف

    keyboard = [
        [InlineKeyboardButton("➕ إضافة متطوع جديد", callback_data='admin_add_volunteer')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # استخدام send_and_track_message لضمان تخزين ID الرسالة للمرة الأولى
    await send_and_track_message(
        update, 
        context,
        '👋 مرحباً بك يا مشرف!\n\n'
        'لوحة تحكم المتطوعين:',
        reply_markup=reply_markup
    )
    return ADMIN_MENU

async def admin_add_volunteer_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """مطالبة المشرف بإدخال الاسم الكامل"""
    query = update.callback_query
    await query.answer()

    keyboard = [[InlineKeyboardButton("🔙 عودة للقائمة الرئيسية", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await query.edit_message_text(
        '➕ إضافة متطوع جديد\n\n'
        'الرجاء إدخال **الاسم الكامل للمتطوع** (كما سيظهر في القوائم):',
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    context.user_data['last_bot_message_id'] = message.message_id
    return ADD_VOLUNTEER_FULL_NAME

async def admin_get_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ الاسم الكامل والمطالبة باختيار الفريق مع تنظيف الرسائل"""
    await delete_previous_message(context, update.effective_chat.id)
    context.user_data['new_volunteer_full_name'] = update.message.text
    
    teams = get_all_teams()
    
    if not teams:
        await update.message.reply_text(
            '❌ لا توجد فرق مسجلة في قاعدة البيانات حالياً!\n'
            'الرجاء إضافة فرق يدوياً أولاً ثم المحاولة مرة أخرى عبر /admin.'
        )
        return await admin_start(update, context)

    # إنشاء أزرار الفرق ديناميكياً
    keyboard = [[InlineKeyboardButton(team['name'], callback_data=f"team_id|{team['id']}")] for team in teams]
    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='back_to_menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await send_and_track_message(
        update, 
        context,
        f"تم تسجيل الاسم: {update.message.text}\n\n"
        "الرجاء اختيار **الفريق** الذي سينضم إليه المتطوع:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return ADD_VOLUNTEER_SELECT_TEAM

async def admin_select_team(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ الفريق والمطالبة برقم معرف تيليجرام"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('|')
    team_id = int(data[1])
    
    # جلب اسم الفريق
    conn = get_db_connection()
    team_row = conn.execute("SELECT name FROM Teams WHERE id = ?", (team_id,)).fetchone()
    conn.close()
    team_name = team_row['name'] if team_row else 'غير معروف'
    
    context.user_data['new_volunteer_team_id'] = team_id
    context.user_data['new_volunteer_team_name'] = team_name

    keyboard = [[InlineKeyboardButton("🔙 عودة للقائمة الرئيسية", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await query.edit_message_text(
        f"✅ تم اختيار الفريق: **{team_name}**\n\n"
        "الخطوة الأخيرة: الرجاء إرسال **رقم معرف تيليجرام (Telegram ID)** الخاص بالمتطوع.\n"
        "*(يمكن الحصول عليه عبر بوتات مثل @userinfobot)*\n\n"
        "مثال: `123456789`",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    context.user_data['last_bot_message_id'] = message.message_id
    return ADD_VOLUNTEER_FINALIZE

async def admin_finalize_volunteer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """استلام رقم تيليجرام وحفظ المتطوع في القاعدة"""
    await delete_previous_message(context, update.effective_chat.id)
    telegram_id_str = update.message.text
    
    
    # التحقق من أن الإدخال هو رقم
    if not telegram_id_str.isdigit():
        keyboard = [[InlineKeyboardButton("🔙 عودة للقائمة الرئيسية", callback_data='back_to_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            '❌ **إدخال غير صالح!**\n'
            'الرجاء إدخال رقم معرف تيليجرام **فقط** (مثال: 123456789).',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        # العودة لنفس الخطوة
        return ADD_VOLUNTEER_FINALIZE
        
    telegram_id = int(telegram_id_str)
    full_name = context.user_data.get('new_volunteer_full_name')
    team_id = context.user_data.get('new_volunteer_team_id')
    team_name = context.user_data.get('new_volunteer_team_name')

    # إضافة إلى قاعدة البيانات
    success = add_new_volunteer_to_db(telegram_id, full_name, team_id)
    
    keyboard = [[InlineKeyboardButton("📝 طلب جديد", callback_data='new_request')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if success:
        await update.message.reply_text(
            f"✅ **تمت إضافة المتطوع بنجاح!**\n\n"
            f"• الاسم: **{full_name}**\n"
            f"• الفريق: **{team_name}**\n"
            f"• معرف تيليجرام: `{telegram_id}`",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"❌ **فشل في إضافة المتطوع!**\n\n"
            f"هناك متطوع آخر مسجل بالفعل بنفس رقم معرف تيليجرام (`{telegram_id}`).\n"
            f"الرجاء التحقق من الرقم والمحاولة مرة أخرى عبر /admin.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    context.user_data.clear()
    return ConversationHandler.END


# --------------------------------- دوال التحكم والإجراءات ---------------------------------

async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة أزرار الموافقة/الرفض في رسالة المشرف"""
    query = update.callback_query
    await query.answer()

    data = query.data.split('|')
    action = data[1]
    request_type = data[2]
    request_id = data[3]
    user_id = data[4]

    admin_user = query.from_user
    request_title = get_request_title(request_type)

    try:
        if action == 'approve':
            user_notification = f'✅ تهانينا! تمت **الموافقة** على {request_title} الخاص بك برقم `{request_id}`.'
        else:
            user_notification = (
                f'❌ نعتذر! تم **رفض** {request_title} الخاص بك برقم `{request_id}`.\n'
                f'للاستعلام عن السبب، يرجى **مراسلة {HR_CONTACT_INFO}**.'
            )

        await context.bot.send_message(
            chat_id=user_id,
            text=user_notification,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"خطأ في إرسال الإشعار للمستخدم {user_id}: {e}")

    status_text = "تمت الموافقة ✅" if action == 'approve' else "تم الرفض ❌"

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
            reply_markup=None, 
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"خطأ في تحديث رسالة المشرف: {e}")

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """العودة للقائمة الرئيسية - يتم استدعاؤها عبر CallbackQueryHandler"""
    query = update.callback_query
    if query:
        await query.answer()
        
    # هنا يتم تنظيف الرسالة التي تم الضغط على الزر فيها
    context.user_data.clear()
    
    # نحافظ على استخدام start، وهي تقوم بـ edit_message_text أو send_message
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

# --------------------------------- التهيئة والتشغيل ---------------------------------

application = None

def initialize_application() -> None:
    """
    تقوم بإعداد كائن التطبيق (Application) وإضافة جميع الـ Handlers.
    تُنفذ مرة واحدة فقط عند بدء تشغيل الخادم.
    """
    global application 
    
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        raise ValueError("BOT_TOKEN or ADMIN_CHAT_ID environment variables not set.")

    # تهيئة قاعدة البيانات
    setup_database()

    # 1. بناء التطبيق
    application = Application.builder().token(BOT_TOKEN).build()

    # 2. إضافة الـ Handlers
    # يجب تعريف معالج العودة للقائمة الرئيسية أولاً لضمان وجوده في نطاق الكونفرزيشن
    back_to_menu_handler = CallbackQueryHandler(back_to_menu, pattern='^back_to_menu$')
    text_message_filter = filters.TEXT & ~filters.COMMAND
    
    admin_action_handler = CallbackQueryHandler(handle_admin_action, pattern=r'^action\|(approve|reject)\|.+$')
    
    # حذف معالج admin_command_handler الخارجي لضمان عدم تداخل تدفق المحادثة
    # application.add_handler(CommandHandler('admin', admin_start))

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('admin', admin_start), 
            CallbackQueryHandler(new_request_handler, pattern='^new_request$')
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_choice, pattern='^(apology|leave|feedback|problem|motivational_gift|references_menu)$') 
            ],
            
            # حالات الطلبات الأساسية (back_to_menu_handler مُدرج أولاً)
            FIRST_NAME: [back_to_menu_handler, MessageHandler(text_message_filter, first_name)],
            LAST_NAME: [back_to_menu_handler, MessageHandler(text_message_filter, last_name)],
            TEAM_NAME: [back_to_menu_handler, MessageHandler(text_message_filter, team_name)],
            
            # حالات مسار الاعتذار
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

            # حالات مسار الإجازة
            LEAVE_START_DATE: [back_to_menu_handler, MessageHandler(text_message_filter, leave_start_date)],
            LEAVE_END_DATE: [back_to_menu_handler, MessageHandler(text_message_filter, leave_end_date)],
            LEAVE_REASON: [back_to_menu_handler, MessageHandler(text_message_filter, leave_reason)],
            LEAVE_NOTES: [
                back_to_menu_handler,
                CallbackQueryHandler(leave_notes, pattern='^skip_leave_notes$'),
                MessageHandler(text_message_filter, leave_notes)
            ],

            # حالات مسار المشاكل
            PROBLEM_DESCRIPTION: [back_to_menu_handler, MessageHandler(text_message_filter, problem_description)],
            PROBLEM_NOTES: [
                back_to_menu_handler,
                CallbackQueryHandler(problem_notes, pattern='^skip_problem_notes$'),
                MessageHandler(text_message_filter, problem_notes)
            ],

            # حالات مسار الاقتراحات
            FEEDBACK_MESSAGE: [back_to_menu_handler, MessageHandler(text_message_filter, feedback_message)],
            
            # حالات المشرف
            ADMIN_MENU: [
                # تم التأكد من أن هذا المعالج يلتقط الزر ويعمل
                CallbackQueryHandler(admin_add_volunteer_prompt, pattern='^admin_add_volunteer$'),
                back_to_menu_handler, # العودة للقائمة الرئيسية
            ],
            ADD_VOLUNTEER_FULL_NAME: [back_to_menu_handler, MessageHandler(text_message_filter, admin_get_full_name)],
            ADD_VOLUNTEER_SELECT_TEAM: [
                back_to_menu_handler, 
                CallbackQueryHandler(admin_select_team, pattern=r'^team_id\|\d+$')
            ],
            ADD_VOLUNTEER_FINALIZE: [back_to_menu_handler, MessageHandler(text_message_filter, admin_finalize_volunteer)],
            
            # حالة المراجع الجديدة
            REFERENCES_MENU: [back_to_menu_handler] 
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(conv_handler)
    application.add_handler(admin_action_handler)
    
    # 3. إعداد الـ Webhook
    if WEBHOOK_URL:
        application.run_webhook( 
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
        logger.info(f"الويب هوك تم إعداده: {WEBHOOK_URL}/{BOT_TOKEN}")

# ** يتم استدعاء دالة التهيئة عند تحميل الوحدة (Module) **
initialize_application()


# --------------------------------- دالة WSGI الوسيطة (لتشغيل Gunicorn) ---------------------------------
def wsgi_app(environ, start_response):
    """
    دالة WSGI الوسيطة التي يستدعيها Gunicorn. 
    """
    if application is None:
        # إذا فشلت التهيئة، أعد 500
        status = '500 INTERNAL SERVER ERROR'
        headers = [('Content-type', 'text/plain')]
        start_response(status, headers)
        return [b"Application not initialized."]
        
    return application.webhooks(environ, start_response)


# --------------------------------- دالة التشغيل المحلية (للتطوير فقط) ---------------------------------

if __name__ == '__main__':
    if not WEBHOOK_URL:
        if application:
            logger.info("يتم التشغيل بـ Polling (تطوير محلي).")
            application.run_polling(allowed_updates=Update.ALL_TYPES)
    else:
        logger.info("تم التهيئة، ومن المتوقع أن يتم التشغيل عبر Gunicorn.")

