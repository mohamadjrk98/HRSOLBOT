import os
import time
import sqlite3
import random
import requests
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, BotCommand, InputFile
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
(MAIN_MENU, FULL_NAME, TEAM_NAME,
 APOLOGY_TYPE, INITIATIVE_NAME, APOLOGY_REASON, APOLOGY_NOTES,
 LEAVE_START_DATE, LEAVE_END_DATE, LEAVE_REASON, LEAVE_NOTES,
 FEEDBACK_MESSAGE, PROBLEM_DESCRIPTION, PROBLEM_NOTES,
 ADMIN_MENU, ADD_VOLUNTEER_FULL_NAME, ADD_VOLUNTEER_SELECT_TEAM) = range(17) 

# متغيرات البيئة (Environment Variables)
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID') # يُستخدم لإرسال الطلبات إليه
HR_CONTACT_INFO = os.getenv('HR_CONTACT_INFO', 'مسؤول الموارد البشرية') # رقم أو معرف HR
WEBHOOK_URL = os.getenv('WEBHOOK_URL') # URL للاستضافة الخارجية
PORT = int(os.environ.get('PORT', 5000))

# ثابت لمسار ملف PDF (يجب وضعه في نفس مجلد التشغيل)
REFERENCE_GUIDE_PATH = 'reference_guide.pdf'

# رسالة الذكر
DHIKR_MESSAGE = (
    "سبحان الله 📿\n"
    "الحمدلله\n"
    "لا إله إلا الله\n"
    "الله اكبر\n"
    "اللهم صلي وسلم على سيدنا محمد وعلى اله وصحبه اجمعين"
)

# خيارات الفرق
TEAM_OPTIONS = ["فريق الدعم الأول", "فريق الدعم الثاني", "الفريق المركزي"]

# --------------------------------- قواعد بيانات المستخدمين (لغرض المثال، استخدام SQLite) ---------------------------------

def get_db_connection():
    conn = sqlite3.connect('hr_bot_data.db')
    return conn

def setup_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # جدول المستخدمين
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            team TEXT
        )
    ''')
    conn.commit()
    conn.close()

# --------------------------------- لوحات المفاتيح (Keyboards) ---------------------------------

def get_main_menu_keyboard():
    """لوحة المفاتيح الرئيسية للمستخدم المسجل."""
    keyboard = [
        [InlineKeyboardButton("طلب إجازة 🌴", callback_data='request_leave'),
         InlineKeyboardButton("إعتذار/مبادرة 📝", callback_data='request_apology')],
        [InlineKeyboardButton("الإبلاغ عن مشكلة/إقتراح 💡", callback_data='report_problem')],
        [InlineKeyboardButton("المراجع والمستندات 📄", callback_data='show_references'),
         InlineKeyboardButton("لا تنسى ذكر الله 📿", callback_data='dhikr_reminder')],
        [InlineKeyboardButton(f"المطور: @Mohamadhj98 🧑‍💻", url="https://t.me/Mohamadhj98")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_menu_keyboard():
    """لوحة المفاتيح للمشرفين."""
    keyboard = [
        [InlineKeyboardButton("إدارة المتطوعين ➕", callback_data='admin_manage_volunteers')],
        [InlineKeyboardButton("إغلاق قائمة المشرف ❌", callback_data='cancel')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_team_selection_keyboard(prefix):
    """لوحة المفاتيح لاختيار الفريق."""
    keyboard = [[InlineKeyboardButton(team, callback_data=f'{prefix}_{team}')] for team in TEAM_OPTIONS]
    keyboard.append([InlineKeyboardButton("العودة إلى القائمة الرئيسية 🔙", callback_data='to_main_menu')])
    return InlineKeyboardMarkup(keyboard)

def get_request_action_keyboard(request_id):
    """لوحة المفاتيح لقبول أو رفض الطلب للمشرف."""
    keyboard = [
        [InlineKeyboardButton("✅ قبول", callback_data=f'action_Approved_{request_id}'),
         InlineKeyboardButton("❌ رفض", callback_data=f'action_Rejected_{request_id}')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_to_main_menu_keyboard():
    """لوحة مفاتيح صغيرة للعودة للقائمة الرئيسية."""
    keyboard = [[InlineKeyboardButton("العودة إلى القائمة الرئيسية 🔙", callback_data='to_main_menu')]]
    return InlineKeyboardMarkup(keyboard)

# --------------------------------- وظائف قواعد البيانات ---------------------------------

def get_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT full_name, team FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def register_user(user_id, full_name, team):
    conn = get_db_connection()
    cursor = conn.cursor()
    # تحديث البيانات إذا كان موجوداً، أو إدراج جديد
    cursor.execute('''
        INSERT INTO users (user_id, full_name, team) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET full_name=excluded.full_name, team=excluded.team
    ''', (user_id, full_name, team))
    conn.commit()
    conn.close()

# --------------------------------- Handlers - التسجيل والبدء ---------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ المحادثة ويسأل عن الاسم الكامل أو يعرض القائمة الرئيسية."""
    user_id = update.effective_user.id
    user_data = get_user(user_id)

    if update.message and update.message.text.startswith('/start'):
        # محاولة حذف رسالة الأمر /start لتنظيف الشات
        try:
            await update.effective_message.delete()
        except Exception:
            pass
    
    if user_id == int(ADMIN_CHAT_ID) and update.effective_message.text == '/admin':
        # إذا كان المستخدم هو المشرف وضغط على /admin مباشرة
        return await admin_menu(update, context)

    if user_data:
        # المستخدم مسجل بالفعل
        full_name = user_data[0]
        context.user_data['full_name'] = full_name
        
        reply_text = f"مرحباً بك مجدداً يا {full_name} في القائمة الرئيسية! 👋\n" \
                     "يرجى اختيار نوع الطلب الذي تريده."
        
        await update.effective_message.reply_text(
            reply_text, 
            reply_markup=get_main_menu_keyboard(),
            reply_to_message_id=None # لمنع الرد على رسالة start
        )
        return MAIN_MENU
    else:
        # مستخدم جديد - يبدأ عملية التسجيل
        reply_text = (
            "أهلاً بك في نظام الموارد البشرية الآلي. 👋\n"
            "للبدء، يرجى إرسال **اسمك الكامل**."
        )
        await update.effective_message.reply_text(reply_text, reply_markup=ReplyKeyboardRemove())
        return FULL_NAME

async def get_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يتلقى الاسم الكامل ويرحب بالمستخدم ويطلب اختيار الفريق."""
    full_name = update.message.text.strip()
    context.user_data['full_name'] = full_name
    
    reply_text = f"اهليييين والله يا {full_name}! 👋\n" \
                 "الآن، يرجى اختيار الفريق الذي تعمل ضمنه من القائمة التالية:"
    
    await update.message.reply_text(
        reply_text, 
        reply_markup=get_team_selection_keyboard('team')
    )
    return TEAM_NAME

async def get_team_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يتلقى اختيار الفريق ويسجل المستخدم ويذهب للقائمة الرئيسية."""
    query = update.callback_query
    await query.answer()
    
    team = query.data.split('_')[1]
    user_id = query.from_user.id
    full_name = context.user_data['full_name']

    # تسجيل المستخدم في قاعدة البيانات
    register_user(user_id, full_name, team)

    # مسح بيانات الحالة المؤقتة
    context.user_data.clear() 

    reply_text = f"تم تسجيلك بنجاح! 🎉\n" \
                 f"الاسم: **{full_name}**\n" \
                 f"الفريق: **{team}**\n\n" \
                 "أهلاً بك في القائمة الرئيسية. يرجى اختيار نوع الطلب."
    
    await query.edit_message_text(
        reply_text, 
        reply_markup=get_main_menu_keyboard()
    )
    return MAIN_MENU

# --------------------------------- Handlers - الأوامر العامة ---------------------------------

async def dhikr_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يرسل رسالة التذكير بالذكر."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        DHIKR_MESSAGE,
        reply_markup=get_back_to_main_menu_keyboard()
    )

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يعرض قائمة المشرف إذا كان المستخدم هو المشرف المعرف."""
    user_id = update.effective_user.id
    
    if user_id != int(ADMIN_CHAT_ID):
        # منع وصول غير المشرفين
        await update.effective_message.reply_text("عذراً، هذا الأمر خاص بالمسؤولين فقط.")
        return ConversationHandler.END
        
    reply_text = "مرحباً بك أيها المسؤول! هذه قائمة المهام الإدارية."
    
    # إذا كان تحديث من رسالة
    if update.message:
        await update.message.reply_text(reply_text, reply_markup=get_admin_menu_keyboard())
    # إذا كان تحديث من زر (مثل عند العودة من عملية إدارة المتطوعين)
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(reply_text, reply_markup=get_admin_menu_keyboard())
        
    return ADMIN_MENU

async def contact_dev(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج لزر المطور (في حال أردنا إرسال رسالة مباشرة بدلاً من URL)."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "يمكنك التواصل مع المطور عبر: @Mohamadhj98"
    )

async def to_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يعود بالقائمة إلى MAIN_MENU من أي خطوة."""
    query = update.callback_query
    await query.answer()
    
    # يجب مسح أي بيانات حالة مؤقتة هنا إذا كانت موجودة
    context.user_data.clear()
    
    user_id = query.from_user.id
    user_data = get_user(user_id)
    
    if user_data:
        full_name = user_data[0]
        reply_text = f"تم إلغاء العملية. مرحباً بك مجدداً يا {full_name} في القائمة الرئيسية! 👋\n" \
                     "يرجى اختيار نوع الطلب الذي تريده."
        
        await query.edit_message_text(
            reply_text,
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU
    else:
        # إذا لم يكن مسجلاً، يبدأ عملية التسجيل
        return await start(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يلغي أي عملية ويعيد المستخدم إلى القائمة الرئيسية."""
    # مسح حالة المستخدم
    context.user_data.clear()
    
    query = update.callback_query
    if query:
        await query.answer()
        
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    
    if user_data:
        full_name = user_data[0]
        reply_text = f"تم إلغاء الطلب. مرحباً بك مجدداً يا {full_name} في القائمة الرئيسية! 👋\n" \
                     "يرجى اختيار نوع الطلب الذي تريده."
        
        # إذا كان التحديث من رسالة (مثل /cancel)
        if update.message:
            await update.message.reply_text(
                reply_text, 
                reply_markup=get_main_menu_keyboard(),
                reply_to_message_id=None
            )
        # إذا كان التحديث من زر
        elif query:
            await query.edit_message_text(
                reply_text, 
                reply_markup=get_main_menu_keyboard()
            )

        return MAIN_MENU
    else:
        # إذا لم يكن مسجلاً
        return await start(update, context)

# --------------------------------- Handlers - إرسال الطلبات ---------------------------------

async def send_request_to_admin(context: ContextTypes.DEFAULT_TYPE, request_data: dict, request_type: str):
    """ينشئ رسالة الطلب للمشرف."""
    admin_id = ADMIN_CHAT_ID
    if not admin_id:
        logger.error("ADMIN_CHAT_ID غير مُعرَّف.")
        return

    # إنشاء رقم طلب عشوائي
    request_id = f"{request_type[0]}{int(time.time() * 1000)}"

    user = get_user(request_data['user_id'])
    full_name = user[0] if user else "مستخدم غير مسجل"
    team = user[1] if user else "غير محدد"
    
    message_text = f"📢 **طلب جديد: {request_type}**\n" \
                   f"➖➖➖➖➖➖➖➖➖➖\n" \
                   f"**رقم الطلب:** `{request_id}`\n" \
                   f"**الموظف:** {full_name} (@{request_data['username']})\n" \
                   f"**الفريق:** {team}\n" \
                   f"**التاريخ/التفاصيل:**\n"

    # إضافة تفاصيل خاصة بنوع الطلب
    if request_type == "Leave":
        message_text += f"- **من:** {request_data['start_date']}\n" \
                        f"- **إلى:** {request_data['end_date']}\n" \
                        f"- **السبب:** {request_data['reason']}\n" \
                        f"- **ملاحظات:** {request_data.get('notes', 'لا يوجد')}\n"
    elif request_type == "Apology":
        message_text += f"- **النوع:** {request_data['apology_type']}\n"
        if request_data['apology_type'] == 'مبادرة':
             message_text += f"- **اسم المبادرة:** {request_data['initiative_name']}\n"
        message_text += f"- **السبب:** {request_data['reason']}\n" \
                        f"- **ملاحظات:** {request_data.get('notes', 'لا يوجد')}\n"
    elif request_type == "Problem":
        message_text += f"- **النوع:** الإبلاغ عن مشكلة/إقتراح\n" \
                        f"- **المشكلة:** {request_data['description']}\n" \
                        f"- **ملاحظات:** {request_data.get('notes', 'لا يوجد')}\n"
    elif request_type == "Feedback":
         message_text += f"- **النوع:** إقتراح/ملاحظة\n" \
                         f"- **الرسالة:** {request_data['message']}\n"

    await context.bot.send_message(
        chat_id=admin_id,
        text=message_text,
        reply_markup=get_request_action_keyboard(request_id),
        parse_mode='Markdown'
    )
    return request_id

# --------------------------------- Handlers - قائمة المراجع ---------------------------------

async def handle_references_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يعالج طلب المراجع ويرسل ملف PDF."""
    query = update.callback_query
    await query.answer()

    # محاولة إرسال ملف PDF
    try:
        with open(REFERENCE_GUIDE_PATH, 'rb') as doc_file:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=InputFile(doc_file, filename='Reference_Guide.pdf'),
                caption="📄 تفضل، هذا هو دليل المراجع الرسمي للفريق."
            )
        
        await query.edit_message_text(
            "تم إرسال دليل المراجع. يمكنك العودة للقائمة الرئيسية الآن.",
            reply_markup=get_back_to_main_menu_keyboard()
        )

    except FileNotFoundError:
        await query.edit_message_text(
            "عذراً، ملف المراجع (reference_guide.pdf) غير متوفر حالياً. يرجى مراجعة HR.",
            reply_markup=get_back_to_main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"فشل إرسال ملف PDF: {e}")
        await query.edit_message_text(
            "حدث خطأ أثناء إرسال الملف. حاول مرة أخرى لاحقاً.",
            reply_markup=get_back_to_main_menu_keyboard()
        )

    return MAIN_MENU

# --------------------------------- Handlers - معالجة المشرف للطلبات ---------------------------------

async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعالج قبول أو رفض طلب من قبل المشرف."""
    query = update.callback_query
    await query.answer()
    
    # تحليل البيانات من زر المشرف: action_STATUS_REQUESTID
    try:
        _, new_status, request_id = query.data.split('_')
    except ValueError:
        logger.error(f"تنسيق بيانات زر المشرف غير صحيح: {query.data}")
        return

    # استخراج محتوى الرسالة الأصلية
    original_text = query.message.text
    
    # استخراج نوع الطلب واسم الموظف من النص الأصلي
    # محاولة استخراج نوع الطلب من السطر الأول
    request_type = next((line.split(':')[1].strip().replace('**', '') for line in original_text.splitlines() if line.startswith('📢 **طلب جديد:')), "طلب")
    
    # بناء رسالة تحديث المشرف
    admin_update_text = original_text.replace(
        "📢 **طلب جديد:", 
        f"✅ **تم الرد:" if new_status == 'Approved' else f"❌ **تم الرد:",
    )
    admin_update_text += f"\n\n**الحالة النهائية:** {new_status} (بواسطة: {query.from_user.username or query.from_user.full_name} في {time.strftime('%Y-%m-%d %H:%M:%S')})"
    
    # تحديث رسالة المشرف (عدم حذف الرسالة والحفاظ عليها)
    await query.edit_message_text(
        admin_update_text,
        reply_markup=None, # إزالة أزرار القبول والرفض
        parse_mode='Markdown'
    )

    # إرسال إشعار للمستخدم
    user_notification_text = f"⚠️ تحديث حالة الطلب رقم **{request_id}**:\n" \
                             f"طلبك الخاص بـ **{request_type}** تم **{new_status}** بواسطة المسؤول.\n\n"

    # إضافة رسالة خاصة لقبول الإجازة
    if new_status == 'Approved':
        if 'Leave' in request_type or 'إجازة' in request_type:
            user_notification_text += "نتمنى لك وقتاً سعيداً! لا تغب كثيراً، سنشتاق لك ✨"
        else:
            user_notification_text += "يمكنك المتابعة. شكراً لك!"
    elif new_status == 'Rejected':
        user_notification_text += "يرجى مراجعة مسؤول الموارد البشرية للمزيد من التفاصيل."

    # **ملاحظة:** لا يمكننا تحديد الـ user_id للموظف من النص. يجب تخزينه في DB.
    # لغرض التشغيل السليم، نفترض أن المشرف سيقوم بالرد يدوياً.
    
    return ConversationHandler.END 


# --------------------------------- Handlers - إدارة المتطوعين ---------------------------------

async def admin_manage_volunteers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ مسار إضافة متطوع جديد."""
    query = update.callback_query
    await query.answer()

    reply_text = "لإضافة متطوع جديد، يرجى إرسال **الاسم الكامل** للمتطوع."
    
    await query.edit_message_text(
        reply_text,
        reply_markup=get_back_to_main_menu_keyboard()
    )
    return ADD_VOLUNTEER_FULL_NAME

async def get_volunteer_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يتلقى الاسم الكامل للمتطوع ويطلب اختيار الفريق."""
    full_name = update.message.text.strip()
    context.user_data['temp_volunteer_name'] = full_name
    
    reply_text = f"تم تسجيل اسم المتطوع: **{full_name}**.\n" \
                 "الآن، يرجى اختيار الفريق الذي سيعمل ضمنه المتطوع:"
    
    await update.message.reply_text(
        reply_text, 
        reply_markup=get_team_selection_keyboard('vol_team')
    )
    return ADD_VOLUNTEER_SELECT_TEAM

async def finalize_volunteer_addition(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يسجل المتطوع وينتهي."""
    query = update.callback_query
    await query.answer()

    team = query.data.split('_')[2]
    full_name = context.user_data.pop('temp_volunteer_name', 'غير معروف')

    # رسالة نجاح للمشرف
    reply_text = f"🎉 **تمت عملية التسجيل المنطقي لمتطوع جديد.**\n" \
                 f"**الاسم:** {full_name}\n" \
                 f"**الفريق:** {team}\n\n" \
                 "الآن يمكنك العودة إلى قائمة المشرف."
    
    await query.edit_message_text(
        reply_text, 
        reply_markup=get_admin_menu_keyboard()
    )
    return ADMIN_MENU

# --------------------------------- وظائف التهيئة والتشغيل ---------------------------------

application = None # متغير عام لتطبيق البوت

def initialize_application():
    """يهيئ التطبيق و Handlers."""
    global application

    # 1. التحقق من التوكن
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN غير مُعرَّف. يرجى تعيين متغير البيئة BOT_TOKEN.")
        return
        
    # 2. إعداد قاعدة البيانات
    setup_db()

    # 3. بناء Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Handlers المشرف (يتم إضافته قبل ConversationHandler لتكون له أولوية)
    application.add_handler(CommandHandler('admin', admin_menu))
    
    # معالج أزرار قبول/رفض الطلبات (يجب أن يكون في مجموعة 1)
    application.add_handler(
        CallbackQueryHandler(handle_admin_action, pattern='^action_(Approved|Rejected)_'), 
        group=1
    )
    
    # معالج العودة للقائمة الرئيسية (يجب أن يكون في مجموعة 1)
    application.add_handler(
        CallbackQueryHandler(to_menu_handler, pattern='^to_main_menu$'),
        group=1
    )

    # معالج التذكير بالذكر
    application.add_handler(
        CallbackQueryHandler(dhikr_reminder, pattern='^dhikr_reminder$'),
        group=1
    )

    # Handlers قائمة المشرف (Admin Menu)
    admin_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_menu, pattern='^admin_menu$')],
        states={
            ADMIN_MENU: [
                CallbackQueryHandler(admin_manage_volunteers, pattern='^admin_manage_volunteers$'),
                CallbackQueryHandler(cancel, pattern='^cancel$')
            ],
            ADD_VOLUNTEER_FULL_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_volunteer_full_name),
            ],
            ADD_VOLUNTEER_SELECT_TEAM: [
                CallbackQueryHandler(finalize_volunteer_addition, pattern='^vol_team_'),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel), CallbackQueryHandler(cancel, pattern='^cancel$')],
        map_to_parent={
            MAIN_MENU: MAIN_MENU 
        }
    )
    # application.add_handler(admin_conv_handler) # لا نحتاج لإضافة هذا لعدم استخدامه كدخول

    # Handlers مسار المحادثة الرئيسي (ConversationHandler)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_full_name)],
            TEAM_NAME: [CallbackQueryHandler(get_team_name, pattern='^team_')],
            MAIN_MENU: [
                CallbackQueryHandler(handle_references_menu, pattern='^show_references$'),
            ],
            # دمج مسار إضافة المتطوعين هنا
            ADMIN_MENU: [
                CallbackQueryHandler(admin_manage_volunteers, pattern='^admin_manage_volunteers$'),
                CallbackQueryHandler(cancel, pattern='^cancel$')
            ],
            ADD_VOLUNTEER_FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_volunteer_full_name)],
            ADD_VOLUNTEER_SELECT_TEAM: [CallbackQueryHandler(finalize_volunteer_addition, pattern='^vol_team_')],
        },
        fallbacks=[CommandHandler('cancel', cancel), CallbackQueryHandler(cancel, pattern='^cancel$')],
    )

    application.add_handler(conv_handler)
    
    # 4. إعداد الأوامر المتاحة (Commands)
    application.bot.set_my_commands([
        BotCommand("start", "بدء المحادثة والذهاب للقائمة الرئيسية"),
        BotCommand("cancel", "إلغاء العملية الحالية والعودة"),
        BotCommand("admin", "الوصول إلى قائمة المشرف (للمسؤول فقط)"),
    ])


# ** يتم استدعاء دالة التهيئة عند تحميل الوحدة (Module) **
# 🛑 التعديل هنا: نزيل الاستدعاء في هذا المكان.
# initialize_application() 


# --------------------------------- دالة WSGI الوسيطة (لتشغيل Gunicorn) ---------------------------------
def wsgi_app(environ, start_response):
    """
    دالة WSGI الوسيطة التي يستدعيها Gunicorn. 
    """
    global application
    
    if application is None:
        # إذا لم يتم تهيئة التطبيق بعد (وهذا يحدث عند بدء Gunicorn)
        initialize_application()

    if application is None:
        # إذا فشلت التهيئة، أعد 500
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
            # 🛑 التشغيل باستخدام Webhook أو Polling بناءً على متغير البيئة
            if WEBHOOK_URL:
                # تشغيل Webhook (لبيئات الاستضافة)
                logger.info(f"يتم إعداد الويب هوك: {WEBHOOK_URL}")
                application.run_webhook( 
                    listen="0.0.0.0",
                    port=PORT,
                    url_path=BOT_TOKEN,
                    webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
                )
            else:
                # تشغيل Polling (للتشغيل المحلي)
                logger.info("يتم التشغيل محلياً باستخدام Polling. اضغط Ctrl+C للإيقاف.")
                application.run_polling(poll_interval=1.0)
    else:
        logger.error("BOT_TOKEN غير مُعرَّف. يرجى تعيين متغير البيئة BOT_TOKEN.")

