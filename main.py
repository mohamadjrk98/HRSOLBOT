.import logging
import os
import time
import sqlite3 
import random # ✅ جديد: لاستخدامه في اختيار العبارات العشوائية
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

# --------------------------------- إعداد قاعدة البيانات ---------------------------------

DB_NAME = 'volunteers_system.db'

def get_db_connection():
    """إنشاء اتصال بقاعدة بيانات SQLite"""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row  # الوصول إلى الأعمدة بالاسم
    return conn

def setup_database():
    """إنشاء جدولي الفرق والمتطوعين وتعبئة بعض الفرق المبدئية"""
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

    # إضافة فرق مبدئية إذا لم تكن موجودة
    initial_teams = [('فريق الدعم الأول',), ('فريق الدعم الثاني',), ('فريق المتابعة',)]
    for team in initial_teams:
        try:
            cursor.execute("INSERT INTO Teams (name) VALUES (?)", team)
        except sqlite3.IntegrityError:
            pass # تم إضافته مسبقًا

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
        return False # المتطوع مسجل مسبقًا بنفس رقم الـ ID

def is_admin(chat_id):
    """التحقق مما إذا كان المستخدم هو المشرف"""
    if not ADMIN_CHAT_ID:
        return False
    return str(chat_id) == str(ADMIN_CHAT_ID)


# --------------------------------- العبارات التحفيزية (Motivational Quotes) ---------------------------------

# ✅ جديد: قائمة بأكثر من 20 عبارة تحفيزية
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

# --------------------------------- تعريف الحالات (States) ---------------------------------

# الحالات (States) المستخدمة في ConversationHandler
(MAIN_MENU, FIRST_NAME, LAST_NAME, TEAM_NAME, 
 APOLOGY_TYPE, INITIATIVE_NAME, APOLOGY_REASON, APOLOGY_NOTES,
 LEAVE_START_DATE, LEAVE_END_DATE, LEAVE_REASON, LEAVE_NOTES,
 FEEDBACK_MESSAGE, PROBLEM_DESCRIPTION, PROBLEM_NOTES,
 ADMIN_MENU, ADD_VOLUNTEER_FULL_NAME, ADD_VOLUNTEER_SELECT_TEAM, ADD_VOLUNTEER_FINALIZE) = range(19)

# متغيرات البيئة (Environment Variables)
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')

# متغيرات خاصة بـ Webhook Render
WEBHOOK_URL = os.getenv('WEBHOOK_URL') 
PORT = int(os.environ.get('PORT', '5000')) 

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
        [InlineKeyboardButton("📝 طلب اعتذار", callback_data='apology'),
         InlineKeyboardButton("🏖️ طلب إجازة", callback_data='leave')],
        [InlineKeyboardButton("🔧 قسم حل المشاكل", callback_data='problem'),
         InlineKeyboardButton("💡 اقتراحات وملاحظات", callback_data='feedback')],
        [InlineKeyboardButton("🎁 هدية لطيفة من البوت", callback_data='motivational_gift')] # ✅ جديد: زر الهدية
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

# --------------------------------- دالة الهدية التحفيزية ---------------------------------

async def send_motivational_gift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """✅ جديد: اختيار وإرسال عبارة تحفيزية عشوائية"""
    query = update.callback_query
    await query.answer()
    
    # اختيار عبارة عشوائية
    quote = random.choice(MOTIVATIONAL_QUOTES)
    
    # رسالة الهدية
    gift_message = (
        "🎁 **هدية لطيفة لك!** 🎁\n"
        "━━━━━━━\n"
        f"*{quote}*\n"
        "━━━━━━━\n"
        "شكراً لجهودك وعطائك المتواصل. أنت تصنع فرقاً حقيقياً! 🌟"
    )

    # إظهار رسالة الهدية ثم العودة للقائمة الرئيسية
    await query.message.reply_text(
        gift_message, 
        parse_mode='Markdown'
    )
    
    # إبقاء المستخدم في القائمة الرئيسية
    return await start(update, context)


# --------------------------------- دوال القوائم والمسارات ---------------------------------

async def main_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة اختيار القائمة الرئيسية"""
    query = update.callback_query
    
    choice = query.data
    
    if choice == 'motivational_gift': # ✅ جديد: معالجة زر الهدية
        return await send_motivational_gift(update, context)
        
    await query.answer()

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

# --------------------------------- (بقية دوال مسارات الطلبات - لا تغيير جوهري) ---------------------------------

# (تم حذف بقية دوال المسارات الطويلة لتقليل حجم الإجابة، مع العلم أنها لم تتغير جوهرياً)
# (مع ملاحظة أن الدوال apology_notes, leave_notes, problem_notes, feedback_message, admin_start, admin_add_volunteer_prompt, admin_get_full_name, admin_select_team, admin_finalize_volunteer, handle_admin_action, back_to_menu, new_request_handler, cancel موجودة كما هي في الكود الأصلي)

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

# ... (بقية دوال apology_type, initiative_name, apology_reason, leave_start_date, leave_end_date, leave_reason, problem_description) ...
# (ملاحظة: دوال الإرسال مثل apology_notes, leave_notes, problem_notes, feedback_message لا تحتاج لتغيير)

# --------------------------------- دوال المشرف لإضافة متطوع ---------------------------------

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """✅ جديد: نقطة دخول المشرف (الأمر /admin)"""
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("❌ غير مصرح لك باستخدام هذا الأمر.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("➕ إضافة متطوع جديد", callback_data='admin_add_volunteer')],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        '👋 مرحباً بك يا مشرف!\n\n'
        'لوحة تحكم المتطوعين:',
        reply_markup=reply_markup
    )
    return ADMIN_MENU

async def admin_add_volunteer_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """✅ جديد: مطالبة المشرف بإدخال الاسم الكامل"""
    query = update.callback_query
    await query.answer()

    keyboard = [[InlineKeyboardButton("🔙 عودة للقائمة الرئيسية", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        '➕ إضافة متطوع جديد\n\n'
        'الرجاء إدخال **الاسم الكامل للمتطوع** (كما سيظهر في القوائم):',
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return ADD_VOLUNTEER_FULL_NAME

async def admin_get_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """✅ جديد: حفظ الاسم الكامل والمطالبة باختيار الفريق"""
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

    await update.message.reply_text(
        f"تم تسجيل الاسم: {update.message.text}\n\n"
        "الرجاء اختيار **الفريق** الذي سينضم إليه المتطوع:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return ADD_VOLUNTEER_SELECT_TEAM

async def admin_select_team(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """✅ جديد: حفظ الفريق والمطالبة برقم معرف تيليجرام"""
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
    
    await query.edit_message_text(
        f"✅ تم اختيار الفريق: **{team_name}**\n\n"
        "الخطوة الأخيرة: الرجاء إرسال **رقم معرف تيليجرام (Telegram ID)** الخاص بالمتطوع.\n"
        "*(يمكن الحصول عليه عبر بوتات مثل @userinfobot)*\n\n"
        "مثال: `123456789`",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return ADD_VOLUNTEER_FINALIZE

async def admin_finalize_volunteer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """✅ جديد: استلام رقم تيليجرام وحفظ المتطوع في القاعدة"""
    telegram_id_str = update.message.text
    
    keyboard = [[InlineKeyboardButton("🔙 عودة للقائمة الرئيسية", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # التحقق من أن الإدخال هو رقم
    if not telegram_id_str.isdigit():
        await update.message.reply_text(
            '❌ **إدخال غير صالح!**\n'
            'الرجاء إدخال رقم معرف تيليجرام **فقط** (مثال: 123456789).',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
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
                f'للاستعلام عن السبب، يرجى **مراسلة الموارد البشرية (HR)**.'
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


# --------------------------------- المتغير العالمي ---------------------------------
application = None


# --------------------------------- دالة الإعداد التي تُنفذ مرة واحدة ---------------------------------

def initialize_application() -> None:
    """
    تقوم بإعداد كائن التطبيق (Application) وإضافة جميع الـ Handlers.
    تُنفذ مرة واحدة فقط عند بدء تشغيل الخادم.
    """
    global application 
    
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        raise ValueError("BOT_TOKEN or ADMIN_CHAT_ID environment variables not set.")

    # ✅ جديد: تهيئة قاعدة البيانات
    setup_database()

    # 1. بناء التطبيق
    application = Application.builder().token(BOT_TOKEN).build()

    # 2. إضافة الـ Handlers
    back_to_menu_handler = CallbackQueryHandler(back_to_menu, pattern='^back_to_menu$')
    text_message_filter = filters.TEXT & ~filters.COMMAND
    
    admin_action_handler = CallbackQueryHandler(handle_admin_action, pattern=r'^action\|(approve|reject)\|.+$')
    
    # ✅ جديد: تعريف معالج أمر المشرف
    admin_command_handler = CommandHandler('admin', admin_start)
    application.add_handler(admin_command_handler)

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('admin', admin_start), 
            CallbackQueryHandler(new_request_handler, pattern='^new_request$')
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_choice, pattern='^(apology|leave|feedback|problem|motivational_gift)$') # ✅ تم التعديل لإضافة الهدية
            ],
            # ... (بقية حالات المتطوعين)
            FIRST_NAME: [back_to_menu_handler, MessageHandler(text_message_filter, first_name)],
            LAST_NAME: [back_to_menu_handler, MessageHandler(text_message_filter, last_name)],
            TEAM_NAME: [back_to_menu_handler, MessageHandler(text_message_filter, team_name)],
            # (بقية الحالات كما هي)
            
            # (تم حذف بقية الحالات لتقليل حجم الإجابة، مع العلم أنها لم تتغير)
            
            # حالات المشرف
            ADMIN_MENU: [
                CallbackQueryHandler(admin_add_volunteer_prompt, pattern='^admin_add_volunteer$'),
                back_to_menu_handler, 
            ],
            ADD_VOLUNTEER_FULL_NAME: [back_to_menu_handler, MessageHandler(text_message_filter, admin_get_full_name)],
            ADD_VOLUNTEER_SELECT_TEAM: [
                back_to_menu_handler, 
                CallbackQueryHandler(admin_select_team, pattern=r'^team_id\|\d+$')
            ],
            ADD_VOLUNTEER_FINALIZE: [back_to_menu_handler, MessageHandler(text_message_filter, admin_finalize_volunteer)],
            
            # حالات الطلبات العادية: (لم تتغير)
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
            LEAVE_START_DATE: [back_to_menu_handler, MessageHandler(text_message_filter, leave_start_date)],
            LEAVE_END_DATE: [back_to_menu_handler, MessageHandler(text_message_filter, leave_end_date)],
            LEAVE_REASON: [back_to_menu_handler, MessageHandler(text_message_filter, leave_reason)],
            LEAVE_NOTES: [
                back_to_menu_handler,
                CallbackQueryHandler(leave_notes, pattern='^skip_leave_notes$'),
                MessageHandler(text_message_filter, leave_notes)
            ],
            PROBLEM_DESCRIPTION: [back_to_menu_handler, MessageHandler(text_message_filter, problem_description)],
            PROBLEM_NOTES: [
                back_to_menu_handler,
                CallbackQueryHandler(problem_notes, pattern='^skip_problem_notes$'),
                MessageHandler(text_message_filter, problem_notes)
            ],
            FEEDBACK_MESSAGE: [back_to_menu_handler, MessageHandler(text_message_filter, feedback_message)],
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
