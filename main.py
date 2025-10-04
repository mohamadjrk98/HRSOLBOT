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

# ... جميع الدوال كما في الكود السابق حتى دالة problem_notes ...

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
        f'🔖 رقم الطلب: `{{request_id}}`\n\n'
        f'📋 **ملخص البلاغ:**\n'
        f'• الوصف: {{problem_description}}\n'
        f'• ملاحظات: {{problem_notes}}\n\n'
        f'سيتم النظر في المشكلة وإبلاغك بالتحديثات.\n\n'
        f'🎉 أهلاً بك في قسم الدعم الفني! سنسعى جاهدين لمساعدتك في أقرب وقت ممكن. شكراً لك على تعاونك معنا!'
    )

    admin_message = (
        f'🔧 **بلاغ مشكلة جديد**\n'
        f'━━━━━━━━━━━━━━━━━\n'
        f'🔖 رقم الطلب: `{{request_id}}`\n'
        f'👤 المبلغ: {{user.first_name}} {{user.last_name or ""}}\n'
        f'🆔 المعرف: @{{user.username or "لا يوجد"}}\n'
        f'🆔 رقم المستخدم: {{user.id}}\n\n'
        f'📋 **التفاصيل:**\n'
        f'• وصف المشكلة: {{problem_description}}\n'
        f'• ملاحظات: {{problem_notes}}\n'
        f'━━━━━━━━━━━━━━━━━'
    )
    
    admin_keyboard = [
        [
            InlineKeyboardButton("✅ تم الحل", callback_data=f'action|approve|{{request_type}}|{{request_id}}|{{user_id}}'),
            InlineKeyboardButton("❌ غير منطبقة", callback_data=f'action|reject|{{request_type}}|{{request_id}}|{{user_id}}')
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

# ... أكمل باقي الكود كما هو ...

def main() -> None:
    setup_database()
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN غير متوفر. يرجى التأكد من تعيين متغير البيئة.")
        return

    application = Application.builder().token(BOT_TOKEN).build()
    
    main_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start), CommandHandler("admin", admin_menu_start, filters=filters.Chat(chat_id=ADMIN_CHAT_ID))],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(handle_callback_query, pattern='^apology$|^leave$|^problem$|^feedback$|^admin_menu$')
            ],
            FIRST_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), first_name)],
            LAST_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), last_name)],
            TEAM_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), team_name)],
            APOLOGY_TYPE: [CallbackQueryHandler(apology_type, pattern='^meeting$|^initiative$|^other$')],
            INITIATIVE_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), initiative_name)],
            APOLOGY_REASON: [MessageHandler(filters.TEXT & (~filters.COMMAND), apology_reason)],
            APOLOGY_NOTES: [
                MessageHandler(filters.TEXT & (~filters.COMMAND), apology_notes),
                CallbackQueryHandler(apology_notes, pattern='^skip_apology_notes$')
            ],
            LEAVE_START_DATE: [MessageHandler(filters.TEXT & (~filters.COMMAND), leave_start_date)],
            LEAVE_END_DATE: [MessageHandler(filters.TEXT & (~filters.COMMAND), leave_end_date)],
            LEAVE_REASON: [MessageHandler(filters.TEXT & (~filters.COMMAND), leave_reason)],
            LEAVE_NOTES: [
                MessageHandler(filters.TEXT & (~filters.COMMAND), leave_notes),
                CallbackQueryHandler(leave_notes, pattern='^skip_leave_notes$')
            ],
            PROBLEM_DESCRIPTION: [MessageHandler(filters.TEXT & (~filters.COMMAND), problem_description)],
            PROBLEM_NOTES: [
                MessageHandler(filters.TEXT & (~filters.COMMAND), problem_notes),
                CallbackQueryHandler(problem_notes, pattern='^skip_problem_notes$')
            ],
            FEEDBACK_MESSAGE: [MessageHandler(filters.TEXT & (~filters.COMMAND), feedback_message)],
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_choice, pattern='^add_volunteer$|^view_volunteers$')
            ],
            ADD_VOLUNTEER_FULL_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), add_volunteer_full_name)],
            ADD_VOLUNTEER_TELEGRAM_ID: [MessageHandler(filters.TEXT & (~filters.COMMAND), add_volunteer_telegram_id)],
            ADD_VOLUNTEER_SELECT_TEAM: [CallbackQueryHandler(add_volunteer_select_team, pattern='^' + re.escape('team_select|'))]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(handle_callback_query, pattern='^back_to_menu$'),
            CallbackQueryHandler(handle_callback_query, pattern='^admin_menu$')
        ]
    )
    application.add_handler(main_conv)
    application.add_handler(CallbackQueryHandler(handle_callback_query))

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