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

# قائمة لمعرفات المدراء/المشرفين المسموح لهم باستخدام لوحة التحكم
# يجب تحديد هذه المعرفات في متغير بيئة أو قاعدة بيانات في بيئة الإنتاج
ADMIN_USER_IDS = [int(id.strip()) for id in os.getenv('ADMIN_USER_IDS', '').split(',') if id.strip().isdigit()]
# يمكن استخدام معرف الـ ADMIN_CHAT_ID كمعرف مسؤول مؤقت إذا لم يتم تحديد قائمة
if ADMIN_CHAT_ID and ADMIN_CHAT_ID.isdigit() and int(ADMIN_CHAT_ID) not in ADMIN_USER_IDS:
    ADMIN_USER_IDS.append(int(ADMIN_CHAT_ID))


# --------------------------------- وظائف قواعد البيانات والمستخدم ---------------------------------

# اسم قاعدة البيانات
DATABASE_NAME = 'bot_data.db'

def init_db():
    """تهيئة قاعدة البيانات وإنشاء الجداول إذا لم تكن موجودة."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    # جدول المستخدمين
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            team_name TEXT,
            registration_date TEXT
        )
    """)
    
    # جدول الطلبات (إجازة، اعتذار، إلخ)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            request_type TEXT NOT NULL,
            status TEXT NOT NULL,
            data TEXT, -- لتخزين البيانات كـ JSON
            submission_date TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    """)
    
    conn.commit()
    conn.close()

def get_db_user(user_id):
    """جلب بيانات المستخدم من قاعدة البيانات."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, first_name, last_name, team_name FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()
    conn.close()
    if user_data:
        return {
            'user_id': user_data[0],
            'first_name': user_data[1],
            'last_name': user_data[2],
            'team_name': user_data[3]
        }
    return None

def register_db_user(user_id, first_name, last_name, team_name):
    """تسجيل مستخدم جديد في قاعدة البيانات."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    try:
        cursor.execute("""
            INSERT INTO users (user_id, first_name, last_name, team_name, registration_date) 
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, first_name, last_name, team_name, timestamp))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"محاولة تسجيل مستخدم موجود: {user_id}")
        return False
    finally:
        conn.close()

def update_db_user_data(user_id, data):
    """تحديث بيانات المستخدم (مثل الفريق أو الاسم)."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    set_clauses = ', '.join([f"{key} = ?" for key in data.keys()])
    values = list(data.values())
    values.append(user_id)
    cursor.execute(f"UPDATE users SET {set_clauses} WHERE user_id = ?", values)
    conn.commit()
    conn.close()

def save_request(user_id, request_type, data):
    """حفظ طلب جديد في قاعدة البيانات."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("""
        INSERT INTO requests (user_id, request_type, status, data, submission_date) 
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, request_type, 'Pending', json.dumps(data), timestamp))
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return request_id

def get_pending_request(request_id):
    """جلب بيانات طلب معلق بواسطة المعرف."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.request_id, r.user_id, r.request_type, r.data, u.first_name, u.last_name, u.team_name
        FROM requests r
        JOIN users u ON r.user_id = u.user_id
        WHERE r.request_id=? AND r.status='Pending'
    """, (request_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {
            'request_id': result[0],
            'user_id': result[1],
            'request_type': result[2],
            'data': json.loads(result[3]),
            'first_name': result[4],
            'last_name': result[5],
            'team_name': result[6]
        }
    return None

def update_request_status(request_id, status, admin_notes=None):
    """تحديث حالة الطلب (مقبول/مرفوض)."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    update_data = {'status': status}
    if admin_notes:
        update_data['admin_notes'] = admin_notes
    
    # يجب جلب البيانات الحالية وتحديثها إذا لزم الأمر
    cursor.execute("SELECT data FROM requests WHERE request_id=?", (request_id,))
    current_data_json = cursor.fetchone()
    
    if current_data_json:
        current_data = json.loads(current_data_json[0])
        current_data.update(update_data)
        
        cursor.execute("UPDATE requests SET status=?, data=? WHERE request_id=?", 
                       (status, json.dumps(current_data), request_id))
        conn.commit()
    conn.close()


# --------------------------------- الدوال المساعدة ---------------------------------

async def reply_to_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None, parse_mode='HTML'):
    """دالة مساعدة لإرسال رسالة إلى المحادثة الحالية وحفظ معرفها."""
    # لتنظيف المحادثة قبل إرسال رسالة جديدة.
    if context.user_data.get('last_bot_message_id'):
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['last_bot_message_id']
            )
        except Exception:
            # نتجاهل الأخطاء إذا فشل حذف الرسالة (مثل الرسائل القديمة جداً)
            pass

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
    
    # 1. معالجة تحديثات CallbackQuery (عند الضغط على الأزرار المضمنة)
    query = update.callback_query
    if query:
        await query.answer()
        user = query.from_user
        message = query.message
    else:
        user = update.effective_user
        message = update.message

    # 2. تحديد هوية المستخدم والتحقق من التسجيل
    
    # إذا لم يكن أول رسالة start/ محاولة حذف رسالة الأمر
    # *** تم إصلاح خطأ AttributeError هنا: message.chat.last_message تم حذفه ***
    if message.text and message.text.startswith('/start'):
        try:
            # محاولة حذف رسالة /start لتنظيف الشات
            await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
        except Exception:
            # لا يهم إذا فشل الحذف
            pass
            
    
    # تنظيف بيانات المستخدم ما عدا بيانات المشرف
    for key in list(context.user_data.keys()):
        if key not in ['admin_mode', 'is_admin']:
            del context.user_data[key]

    
    # جلب بيانات المستخدم من DB
    user_data = get_db_user(user.id)
    if not user_data:
        # إذا لم يكن مسجلاً، اطلب التسجيل
        context.user_data['user_id'] = user.id
        await reply_to_chat(update, context, f"أهلاً {user.first_name}!\n\nيبدو أنك لم تسجل بعد. الرجاء إدخال اسمك الأول للبدء:", 
                            reply_markup=ReplyKeyboardRemove())
        return FIRST_NAME
    
    # تخزين بيانات المستخدم المسجل
    context.user_data.update(user_data)


    # إنشاء لوحة المفاتيح الرئيسية
    keyboard = [
        [InlineKeyboardButton("📝 طلب اعتذار", callback_data='apology'),
         InlineKeyboardButton("🌴 طلب إجازة", callback_data='leave')],
        [InlineKeyboardButton("🛠️ قسم المشاكل", callback_data='problem'),
         InlineKeyboardButton("💡 اقتراحات وملاحظات", callback_data='feedback')],
        [InlineKeyboardButton("📚 مراجع الفريق", callback_data='references_menu'),
         InlineKeyboardButton("🎁 هدية لطيفة", callback_data='motivation')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = f"""
أهلاً {user.first_name}! 👋
أنا بوت طلبات المتطوعين. كيف يمكنني مساعدتك اليوم؟

لإلغاء الطلب في أي وقت، أرسل /cancel
"""

    await reply_to_chat(update, context, text, reply_markup=reply_markup)
    return MAIN_MENU

# دالة لتحديد اسم الفريق (مؤقتة للتسجيل)
TEAM_OPTIONS = ["المحاسبة", "التسويق", "التصميم", "البرمجة", "المحتوى"] 

async def get_first_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الأولى في التسجيل: حفظ الاسم الأول."""
    context.user_data['first_name'] = update.message.text.strip()
    await reply_to_chat(update, context, "تمام. الآن، من فضلك أدخل اسمك الأخير:")
    return LAST_NAME

async def get_last_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الثانية في التسجيل: حفظ الاسم الأخير."""
    context.user_data['last_name'] = update.message.text.strip()
    
    # إنشاء لوحة مفاتيح لاختيار الفريق
    keyboard = [[InlineKeyboardButton(team, callback_data=f"team_{team}")] for team in TEAM_OPTIONS]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await reply_to_chat(update, context, "شكراً لك. الآن، من فضلك اختر فريقك:", reply_markup=reply_markup)
    return TEAM_NAME

async def finalize_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الثالثة والأخيرة في التسجيل: حفظ الفريق وتسجيل المستخدم."""
    query = update.callback_query
    await query.answer()
    
    team_name = query.data.replace('team_', '')
    context.user_data['team_name'] = team_name
    
    user_id = context.user_data['user_id']
    first_name = context.user_data['first_name']
    last_name = context.user_data['last_name']
    
    register_db_user(user_id, first_name, last_name, team_name)
    
    await start(update, context) # العودة إلى القائمة الرئيسية
    return MAIN_MENU


# --------------------------------- وظائف الإجازات والاعتذارات (نماذج) ---------------------------------

async def handle_leave_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """بدء طلب الإجازة: طلب تاريخ البدء."""
    # (التحقق من أن المستخدم مسجل يتم في دالة start)
    await reply_to_chat(update, context, "حسناً، لتقديم طلب إجازة. من فضلك أدخل تاريخ بدء الإجازة (بصيغة DD/MM/YYYY):")
    return LEAVE_START_DATE

async def get_leave_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ تاريخ البدء وطلب تاريخ الانتهاء."""
    # هنا يجب إضافة التحقق من صحة صيغة التاريخ
    context.user_data['leave_start_date'] = update.message.text.strip()
    await reply_to_chat(update, context, "شكراً. الآن، أدخل تاريخ انتهاء الإجازة (بصيغة DD/MM/YYYY):")
    return LEAVE_END_DATE

async def get_leave_end_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ تاريخ الانتهاء وطلب سبب الإجازة."""
    # هنا يجب إضافة التحقق من صحة التاريخ (مثل التأكد من أن تاريخ الانتهاء بعد تاريخ البدء)
    context.user_data['leave_end_date'] = update.message.text.strip()
    await reply_to_chat(update, context, "ما هو سبب الإجازة؟")
    return LEAVE_REASON

async def get_leave_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ سبب الإجازة وطلب أي ملاحظات إضافية."""
    context.user_data['leave_reason'] = update.message.text.strip()
    await reply_to_chat(update, context, "هل لديك أي ملاحظات إضافية بخصوص الإجازة؟ (أو أرسل 'لا'):")
    return LEAVE_NOTES

async def finalize_leave_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """تجميع بيانات الإجازة وإرسالها إلى الإدارة."""
    context.user_data['leave_notes'] = update.message.text.strip()
    
    data = {
        'start_date': context.user_data['leave_start_date'],
        'end_date': context.user_data['leave_end_date'],
        'reason': context.user_data['leave_reason'],
        'notes': context.user_data['leave_notes'],
        'user_chat_id': update.effective_chat.id
    }
    
    # حفظ الطلب في DB والحصول على معرّف الطلب
    request_id = save_request(context.user_data['user_id'], 'Leave', data)
    
    # ------------------- إرسال إشعار للمشرف -------------------
    
    full_name = f"{context.user_data['first_name']} {context.user_data['last_name']}"
    
    admin_text = f"""
🛑 طلب إجازة جديد (ID: {request_id})

**المتطوع:** {full_name}
**الفريق:** {context.user_data.get('team_name', 'غير محدد')}
**من:** {data['start_date']}
**إلى:** {data['end_date']}
**السبب:** {data['reason']}
**ملاحظات:** {data['notes']}
"""
    
    admin_keyboard = [
        [InlineKeyboardButton("✅ قبول الإجازة", callback_data=f'admin_approve_Leave_{request_id}'),
         InlineKeyboardButton("❌ رفض الإجازة", callback_data=f'admin_reject_Leave_{request_id}')]
    ]
    admin_markup = InlineKeyboardMarkup(admin_keyboard)
    
    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_text,
                reply_markup=admin_markup,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"فشل إرسال رسالة للمشرف: {e}")
            
    # إرسال رسالة تأكيد للمستخدم
    await reply_to_chat(update, context, "✅ تم إرسال طلب الإجازة بنجاح! سيتم إخطارك بالرد قريباً.\n\n"
                        "يمكنك العودة إلى القائمة الرئيسية.")
    
    # العودة إلى القائمة الرئيسية
    return await start(update, context) 


# دالة نموذجية للتعامل مع طلب الاعتذار
async def handle_apology_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """بدء طلب الاعتذار: طلب نوع الاعتذار."""
    await reply_to_chat(update, context, "لتقديم طلب اعتذار، من فضلك أدخل نوع الاعتذار (مثلاً: غياب، تأخير، عدم إكمال مهمة):")
    return APOLOGY_TYPE

async def get_apology_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ نوع الاعتذار وطلب السبب."""
    context.user_data['apology_type'] = update.message.text.strip()
    await reply_to_chat(update, context, "ما هو سبب هذا الاعتذار؟")
    return APOLOGY_REASON

async def finalize_apology_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """تجميع بيانات الاعتذار وإرسالها (نموذج)."""
    context.user_data['apology_reason'] = update.message.text.strip()

    # حفظ الطلب في DB والحصول على معرّف الطلب (نموذج فقط)
    data = {
        'type': context.user_data['apology_type'],
        'reason': context.user_data['apology_reason'],
        'user_chat_id': update.effective_chat.id
    }
    request_id = save_request(context.user_data['user_id'], 'Apology', data)
    
    # رسالة تأكيد للمستخدم
    await reply_to_chat(update, context, "✅ تم إرسال طلب الاعتذار بنجاح! شكراً على التزامك.")
    
    # العودة إلى القائمة الرئيسية
    return await start(update, context) 

# دالة التعامل مع الأزرار في القائمة الرئيسية
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يُستخدم لمعالجة أزرار القائمة الرئيسية."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == 'leave':
        return await handle_leave_request(update, context)
    elif data == 'apology':
        return await handle_apology_request(update, context)
    elif data == 'problem':
        await reply_to_chat(update, context, "لإبلاغ عن مشكلة، من فضلك صفها بإيجاز:")
        return PROBLEM_DESCRIPTION
    elif data == 'feedback':
        await reply_to_chat(update, context, "لإرسال اقتراح أو ملاحظة، اكتب رسالتك وسنقرأها بتمعن:")
        return FEEDBACK_MESSAGE
    elif data == 'references_menu':
        await reply_to_chat(update, context, "هذه القائمة للمراجع.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("العودة للقائمة", callback_data='to_main_menu')]]))
        return REFERENCES_MENU
    elif data == 'motivation':
        await reply_to_chat(update, context, "أنت تقوم بعمل رائع! شكراً لجهودك! 🌟")
        return MAIN_MENU
    elif data == 'to_main_menu':
        return await start(update, context) # العودة للـ start
    
    return MAIN_MENU

# --------------------------------- وظائف الإدارة (Admin) ---------------------------------

async def is_admin(update: Update) -> bool:
    """التحقق مما إذا كان المستخدم مشرفاً."""
    if update.effective_user and update.effective_user.id in ADMIN_USER_IDS:
        return True
    return False

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """عرض لوحة تحكم المشرف."""
    if not await is_admin(update):
        await update.message.reply_text("⛔ غير مصرح لك بالوصول إلى لوحة التحكم هذه.")
        return ConversationHandler.END

    context.user_data['is_admin'] = True
    
    # في حالة الـ /admin العادية، نحتاج لحذف أمر المشرف ثم إرسال رسالة القائمة
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception:
        pass
        
    keyboard = [
        [InlineKeyboardButton("✅ مراجعة الطلبات المعلقة", callback_data='admin_view_pending')],
        [InlineKeyboardButton("👤 إدارة المتطوعين", callback_data='admin_manage_volunteers')],
        [InlineKeyboardButton("↩️ العودة لقائمة المستخدم", callback_data='to_main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await reply_to_chat(update, context, "لوحة تحكم المشرف 🛠️", reply_markup=reply_markup)
    
    # ننهي المحادثة الحالية ونبدأ المحادثة الإدارية إذا لزم الأمر
    return ADMIN_MENU

async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إجراءات المشرف (قبول/رفض الطلبات)."""
    query = update.callback_query
    await query.answer()

    if not await is_admin(update):
        await query.message.edit_text("⛔ غير مصرح لك بالقيام بهذا الإجراء.")
        return

    data = query.data.split('_') # admin_action_type_request_id
    action = data[1]
    request_type = data[2]
    request_id = int(data[3])

    request = get_pending_request(request_id)

    if not request:
        await query.message.edit_text(f"🛑 الطلب رقم {request_id} لم يعد معلقاً أو غير موجود.")
        return

    # تحديث حالة الطلب في DB
    new_status = 'Approved' if action == 'approve' else 'Rejected'
    update_request_status(request_id, new_status)

    user_chat_id = request['data']['user_chat_id']
    full_name = f"{request['first_name']} {request['last_name']}"

    # إشعار للمتطوع
    user_notification_text = f"🚨 حالة طلبك: **{request_type}** (ID: {request_id})\n\n"
    
    if new_status == 'Approved':
        user_notification_text += "✅ **تم قبول طلبك!**\n\n"
        
        # *** التحديث المطلوب هنا ***
        if request_type == 'Leave':
             user_notification_text += "نتمنى لك وقتاً سعيداً! لا تغب كثيراً، سنشتاق لك ✨"
        else:
             user_notification_text += "يمكنك المتابعة."
    else: # Rejected
        user_notification_text += "❌ **تم رفض طلبك.** يرجى التواصل مع HR.\n"
        user_notification_text += f"للتواصل: {HR_CONTACT_INFO}"

    # إرسال الإشعار للمستخدم الأصلي
    try:
        await context.bot.send_message(
            chat_id=user_chat_id,
            text=user_notification_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"فشل إرسال إشعار للمستخدم {request['user_id']}: {e}")

    # تحديث رسالة المشرف
    await query.message.edit_text(f"✅ تم اتخاذ الإجراء: **{new_status}** لطلب {request_type} رقم {request_id} للمتطوع {full_name}.", parse_mode='Markdown')


# --------------------------------- Fallback و Cancel ---------------------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دالة الإلغاء (يتم استدعاؤها عبر أمر /cancel)."""
    user = update.effective_user
    
    # تنظيف بيانات الجلسة (باستثناء بيانات المشرف)
    for key in list(context.user_data.keys()):
        if key not in ['admin_mode', 'is_admin']:
            del context.user_data[key]
            
    # حذف رسالة /cancel
    if update.message:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        except Exception:
            pass # نتجاهل الفشل

    # إرسال رسالة التأكيد والعودة للقائمة الرئيسية
    await reply_to_chat(update, context, 
                        "❌ تم إلغاء الطلب.\nيمكنك البدء من جديد بإرسال /start.",
                        reply_markup=ReplyKeyboardRemove())
    
    # العودة إلى الحالة صفر
    return ConversationHandler.END

async def to_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دالة مساعدة لمعالجة زر العودة للقائمة الرئيسية."""
    query = update.callback_query
    await query.answer()
    return await start(update, context)

# --------------------------------- دالة التهيئة والتشغيل ---------------------------------

application = None

def initialize_application():
    """تهيئة التطبيق وتجهيز الـ Handlers."""
    global application

    # 0. تهيئة DB
    init_db()

    # 1. إعداد التطبيق
    if not BOT_TOKEN:
        logger.error("خطأ: متغير البيئة BOT_TOKEN غير محدد!")
        return
        
    application = Application.builder().token(BOT_TOKEN).build()
    
    # 2. إعداد الـ Handlers
    
    # ------------------- Handler الإجراءات الإدارية -------------------
    # هذا يجب أن يوضع قبل ConversationHandler لضمان الأولوية
    admin_action_handler = CallbackQueryHandler(handle_admin_action, pattern=r'^admin_(approve|reject)_[A-Za-z]+_\d+$')
    application.add_handler(admin_action_handler)
    
    # ------------------- ConversationHandler للمهام الرئيسية -------------------
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start),
                      CallbackQueryHandler(main_menu_handler, pattern='^(apology|leave|problem|feedback|motivation|references_menu)$')],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_handler, pattern='^(apology|leave|problem|feedback|motivation|references_menu)$')
            ],
            # حالات التسجيل
            FIRST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_first_name)],
            LAST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_last_name)],
            TEAM_NAME: [CallbackQueryHandler(finalize_registration, pattern=r'^team_')],
            
            # حالات طلب الإجازة
            LEAVE_START_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_leave_start_date)],
            LEAVE_END_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_leave_end_date)],
            LEAVE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_leave_reason)],
            LEAVE_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_leave_request)],

            # حالات طلب الاعتذار (نموذج)
            APOLOGY_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_apology_type)],
            APOLOGY_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_apology_request)],
            
            # حالات العودة للقائمة الرئيسية
            REFERENCES_MENU: [CallbackQueryHandler(to_menu_handler, pattern='^to_main_menu$')]
        },
        fallbacks=[CommandHandler('cancel', cancel),
                   CallbackQueryHandler(to_menu_handler, pattern='^to_main_menu$')]
    )
    
    # ------------------- Handler الأوامر العامة (مثل /admin) -------------------
    application.add_handler(CommandHandler('admin', admin_menu))
    
    # *** يجب إضافة ConversationHandler بعد Handlers الأوامر الهامة مثل /admin ***
    application.add_handler(conv_handler)
    
    # 3. إعداد الـ Webhook
    # يتم تجاهل هذا الجزء في بيئة RENDER أو Gunicorn، ولكنه يُترك للتشغيل المحلي
    # if WEBHOOK_URL:
    #     ... (كود الـ Webhook الأصلي) ...
    # else:
    #     application.run_polling(poll_interval=1.0) # للتطوير المحلي

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
    # لتشغيل البوت محلياً (Polling) إذا لم يكن هناك إعداد Webhook
    # يمكن إزالة هذا الجزء في بيئة Gunicorn/RENDER
    if application:
        logger.info("يتم التشغيل محلياً باستخدام Polling. اضغط Ctrl+C للإيقاف.")
        application.run_polling(poll_interval=1.0)

