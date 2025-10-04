import logging
import os
import time
import sqlite3
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
    # تحويل chat_id و ADMIN_CHAT_ID إلى سلاسل نصية للمقارنة الآمنة
    if not ADMIN_CHAT_ID:
        return False
    return str(chat_id) == str(ADMIN_CHAT_ID)


# --------------------------------- تعريف الحالات (States) ---------------------------------

# الحالات (States) المستخدمة في ConversationHandler
(MAIN_MENU, FIRST_NAME, LAST_NAME, TEAM_NAME, 
 APOLOGY_TYPE, INITIATIVE_NAME, APOLOGY_REASON, APOLOGY_NOTES,
 LEAVE_START_DATE, LEAVE_END_DATE, LEAVE_REASON, LEAVE_NOTES,
 FEEDBACK_MESSAGE, PROBLEM_DESCRIPTION, PROBLEM_NOTES,
 ADMIN_MENU, ADD_VOLUNTEER_FULL_NAME, ADD_VOLUNTEER_SELECT_TEAM, ADD_VOLUNTEER_FINALIZE, ADD_VOLUNTEER_TELEGRAM_ID) = range(20)

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
        [InlineKeyboardButton("📝 طلب اعتذار", callback_data='apology')],
        [InlineKeyboardButton("🏖️ طلب إجازة", callback_data='leave')],
        [InlineKeyboardButton("🔧 قسم حل المشاكل", callback_data='problem')],
        [InlineKeyboardButton("💡 اقتراحات وملاحظات", callback_data='feedback')]
    ]

    # إضافة زر لوحة المشرف إذا كان المستخدم هو المدير
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

# --------------------------------- دوال لوحة المشرف ---------------------------------

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """عرض قائمة المشرف"""
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ غير مصرح لك بالدخول إلى هذه القائمة.")
        return MAIN_MENU

    keyboard = [
        [InlineKeyboardButton("➕ إضافة متطوع جديد", callback_data='add_volunteer')],
        [InlineKeyboardButton("📜 عرض المتطوعين (قريباً)", callback_data='view_volunteers')],
        [InlineKeyboardButton("🔙 عودة للقائمة الرئيسية", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "⚙️ **لوحة المشرف**\n\n"
        "ما هي الإجراء الذي ترغب في تنفيذه؟",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return ADMIN_MENU

async def admin_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة خيارات قائمة المشرف"""
    query = update.callback_query
    await query.answer()
    
    choice = query.data
    
    if choice == 'add_volunteer':
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
    """حفظ الاسم الكامل وطلب رقم تعريف تيليجرام"""
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
    """حفظ رقم تعريف تيليجرام وعرض قائمة الفرق"""
    telegram_id_str = update.message.text.strip()
    
    # التحقق من أن المدخل هو رقم
    if not telegram_id_str.isdigit():
        await update.message.reply_text(
            "⚠️ الرجاء إدخال رقم تعريف تيليجرام **صحيح** (رقم فقط).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data='admin_menu')]])
        )
        return ADD_VOLUNTEER_TELEGRAM_ID # البقاء في نفس الحالة

    context.user_data['new_volunteer_telegram_id'] = int(telegram_id_str)
    
    teams = get_all_teams()
    keyboard = []
    
    # بناء أزرار الفرق
    for team in teams:
        # callback_data: team_id|team_name
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
    """معالجة اختيار الفريق وإنهاء عملية الإضافة"""
    query = update.callback_query
    await query.answer()

    # فك تشفير البيانات: team_select|team_id|team_name
    data_parts = query.data.split('|')
    team_id = int(data_parts[1])
    team_name = data_parts[2]
    
    full_name = context.user_data.get('new_volunteer_full_name')
    telegram_id = context.user_data.get('new_volunteer_telegram_id')

    # محاولة الإضافة إلى قاعدة البيانات
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

# --------------------------------- دوال الـ Callbacks (تعديل دالة شاملة) ---------------------------------

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالج شامل لكل ضغطات أزرار Inline Keyboard غير المرتبطة بمحادثة"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # 1. حالة العودة إلى القائمة الرئيسية
    if data == 'back_to_menu' or data == 'new_request':
        # إذا تم ضغط زر عودة، ننهي المحادثة الحالية ونبدأ من جديد
        if context.user_data:
             context.user_data.clear()
             
        return await start(update, context) # يجب أن تعيد الدالة حالة (MAIN_MENU)

    # 2. حالة الدخول إلى قائمة المشرف
    elif data == 'admin_menu':
        return await admin_menu(update, context) # يجب أن تعيد الدالة حالة (ADMIN_MENU)

    # 3. حالة بدأ محادثة إضافة متطوع من قائمة المشرف
    elif data == 'add_volunteer':
        return await admin_menu_choice(update, context) # سيحول الحالة إلى ADD_VOLUNTEER_FULL_NAME

    # 4. حالة اختيار الفريق عند إضافة متطوع (بدون محادثة)
    elif data.startswith('team_select|'):
        # هذه المعالجة تمت ضمن ConversationHandler، لا نحتاجها هنا
        pass 

    # 5. حالة قبول/رفض طلب (للمدير)
    elif data.startswith('action|'):
        # هنا يمكنك معالجة أزرار الموافقة والرفض
        parts = data.split('|')
        action, request_type, request_id, user_id = parts[1], parts[2], parts[3], parts[4]
        
        if is_admin(query.from_user.id):
            user_message = f"تم **{'قبول' if action == 'approve' else 'رفض'}** {get_request_title(request_type)} الخاص بك: `{request_id}`."
            
            try:
                # إرسال إشعار للمستخدم
                await context.bot.send_message(chat_id=user_id, text=user_message, parse_mode='Markdown')
                
                # تعديل رسالة الطلب للمدير
                await query.edit_message_text(
                    query.message.text + 
                    f'\n\n✅ **تم الرد من قبل {query.from_user.first_name}: {action.upper()}**',
                    reply_markup=None,
                    parse_mode='Markdown'
                )
                logger.info(f"تم {action} الطلب {request_id} للمستخدم {user_id}")
            except Exception as e:
                await query.edit_message_text(f"❌ خطأ في إرسال الرد للمستخدم: {e}")
                logger.error(f"خطأ في إرسال الرد للمستخدم {user_id}: {e}")
        else:
            await query.answer("❌ غير مصرح لك باتخاذ هذا الإجراء.")
            
        return MAIN_MENU # ننهي معالجة الـ callback هنا ولا نغير حالة المحادثة

    # 6. تمرير ضغطات الأزرار الأخرى التي تبدأ محادثة إلى الدالة المناسبة
    if data in ['apology', 'leave', 'problem', 'feedback']:
        return await main_menu_choice(update, context)

    return MAIN_MENU

# --------------------------------- دوال القوائم والمسارات ... (بقية الدوال كما هي، لن نكررها) ---------------------------------
# ... (first_name, last_name, team_name, apology_type, initiative_name, apology_reason, apology_notes, leave_start_date, leave_end_date, leave_reason, leave_notes, problem_description, problem_notes, feedback_message)

# (تأكد من أن هذه الدوال مُضافة في ملفك، وهي نفس الدوال التي أرسلتها سابقاً، باستثناء التعديلات على الـ Callbacks)
# ...

# --------------------------------- دالة الإلغاء ---------------------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """إلغاء المحادثة وإرجاع المستخدم للقائمة الرئيسية"""
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


# --------------------------------- الدالة الرئيسية ---------------------------------

def main() -> None:
    """تشغيل البوت"""
    # تهيئة قاعدة البيانات عند بدء التشغيل
    setup_database()
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN غير متوفر. يرجى التأكد من تعيين متغير البيئة.")
        return

    application = Application.builder().token(BOT_TOKEN).build()
    
    # 1. محادثة إضافة المتطوعين (جديدة)
    admin_add_volunteer_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_menu_choice, pattern='^add_volunteer$')],
        states={
            ADD_VOLUNTEER_FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_volunteer_full_name)],
            ADD_VOLUNTEER_TELEGRAM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_volunteer_telegram_id)],
            ADD_VOLUNTEER_SELECT_TEAM: [CallbackQueryHandler(add_volunteer_select_team, pattern='^team_select\|')]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(handle_callback_query, pattern='^admin_menu$'), # العودة لقائمة المدير
            CallbackQueryHandler(handle_callback_query, pattern='^back_to_menu$') # العودة للقائمة الرئيسية
        ],
        map_to_parent={
            ADMIN_MENU: ADMIN_MENU,
            MAIN_MENU: MAIN_MENU,
            ConversationHandler.END: ADMIN_MENU # بعد الانتهاء من الإضافة، يعود المشرف لقائمة المشرف
        }
    )

    # 2. محادثة الطلبات الرئيسية
    main_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(handle_callback_query, pattern='^apology$|^leave$|^problem$|^feedback$|^admin_menu$')
            ],
            FIRST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, first_name)],
            LAST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, last_name)],
            TEAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, team_name)],

            # مسار الاعتذار
            APOLOGY_TYPE: [CallbackQueryHandler(apology_type, pattern='^meeting$|^initiative$|^other$')],
            INITIATIVE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, initiative_name)],
            APOLOGY_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, apology_reason)],
            APOLOGY_NOTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, apology_notes),
                CallbackQueryHandler(apology_notes, pattern='^skip_apology_notes$')
            ],

            # مسار الإجازة
            LEAVE_START_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, leave_start_date)],
            LEAVE_END_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, leave_end_date)],
            LEAVE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, leave_reason)],
            LEAVE_NOTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, leave_notes),
                CallbackQueryHandler(leave_notes, pattern='^skip_leave_notes$')
            ],

            # مسار المشكلة
            PROBLEM_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, problem_description)],
            PROBLEM_NOTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, problem_notes),
                CallbackQueryHandler(problem_notes, pattern='^skip_problem_notes$')
            ],

            # مسار الاقتراح/الملاحظة
            FEEDBACK_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_message)],
            
            # قائمة المدير (مضافة في المحادثة الرئيسية للسماح بالتنقل)
            ADMIN_MENU: [
                admin_add_volunteer_conv, # تضمين محادثة إضافة المتطوعين هنا
                CallbackQueryHandler(admin_menu_choice, pattern='^view_volunteers$')
            ]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(handle_callback_query, pattern='^back_to_menu$'),
            CallbackQueryHandler(handle_callback_query, pattern='^admin_menu$')
        ]
    )
    
    # 3. معالج الـ Callback الشامل (للأزرار التي خارج المحادثات)
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    # 4. إضافة المحادثات
    application.add_handler(main_conv)
    application.add_handler(CommandHandler("admin", admin_menu, filters=filters.Chat(chat_id=ADMIN_CHAT_ID)))

    # 5. تشغيل البوت عبر Webhook (لبيئات الاستضافة مثل Render)
    if WEBHOOK_URL:
        # إعداد Webhook
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f'{WEBHOOK_URL}/{BOT_TOKEN}'
        )
        logger.info(f"البوت يعمل عبر Webhook على البورت {PORT}")
    else:
        # تشغيل عادي (Polling)
        logger.info("البوت يعمل عبر Polling")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
