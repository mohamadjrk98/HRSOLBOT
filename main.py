import os
import time
import sqlite3 
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, InputFile
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
(MAIN_MENU, FULL_NAME_REGISTRATION, TEAM_NAME_SELECTION, 
 APOLOGY_TYPE, APOLOGY_REASON,
 LEAVE_START_DATE, LEAVE_END_DATE, LEAVE_REASON, LEAVE_NOTES,
 FEEDBACK_MESSAGE, PROBLEM_DESCRIPTION,
 ADMIN_MENU, ADD_VOLUNTEER_FULL_NAME, ADD_VOLUNTEER_SELECT_TEAM,
 REFERENCES_MENU) = range(15) 

# متغيرات البيئة والثوابت
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID') # يُستخدم لإرسال الطلبات إليه
HR_CONTACT_INFO = os.getenv('HR_CONTACT_INFO', 'مسؤول الموارد البشرية')
DEVELOPER_USERNAME = "@Mohamadhj98"

# قائمة لمعرفات المدراء/المشرفين المسموح لهم باستخدام لوحة التحكم
ADMIN_USER_IDS = [int(id.strip()) for id in os.getenv('ADMIN_USER_IDS', '').split(',') if id.strip().isdigit()]
if ADMIN_CHAT_ID and ADMIN_CHAT_ID.isdigit() and int(ADMIN_CHAT_ID) not in ADMIN_USER_IDS:
    ADMIN_USER_IDS.append(int(ADMIN_CHAT_ID))

# قائمة الفرق
TEAM_OPTIONS = ["فريق الدعم الأول", "فريق الدعم الثاني", "الفريق المركزي"]

# مسار وهمي لملف PDF (يجب استبداله بمسار حقيقي)
REFERENCE_GUIDE_PATH = 'reference_guide.pdf'

# رسالة الذكر المطلوبة
DHIKR_MESSAGE = """
🕊️ سبحان الله وبحمده سبحان الله العظيم
🕊️ لا إله إلا الله وحده لا شريك له له الملك وله الحمد وهو على كل شيء قدير
🕊️ اللهم صل وسلم وبارك على سيدنا محمد وعلى آله وصحبه أجمعين

"""


# --------------------------------- وظائف قواعد البيانات والمستخدم ---------------------------------

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
            full_name TEXT, 
            team_name TEXT,
            registration_date TEXT
        )
    """)
    
    # جدول الطلبات
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
    cursor.execute("SELECT user_id, first_name, last_name, full_name, team_name FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()
    conn.close()
    if user_data:
        return {
            'user_id': user_data[0],
            'first_name': user_data[1],
            'last_name': user_data[2],
            'full_name': user_data[3],
            'team_name': user_data[4]
        }
    return None

def register_db_user(user_id, full_name, first_name, last_name, team_name):
    """تسجيل مستخدم جديد في قاعدة البيانات."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    try:
        cursor.execute("""
            INSERT INTO users (user_id, first_name, last_name, full_name, team_name, registration_date) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, first_name, last_name, full_name, team_name, timestamp))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"محاولة تسجيل مستخدم موجود: {user_id}")
        return False
    finally:
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
        SELECT r.request_id, r.user_id, r.request_type, r.data, u.full_name, u.team_name
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
            'full_name': result[4],
            'team_name': result[5]
        }
    return None

def update_request_status(request_id, status, admin_notes=None):
    """تحديث حالة الطلب (مقبول/مرفوض)."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT data FROM requests WHERE request_id=?", (request_id,))
    current_data_json = cursor.fetchone()
    
    if current_data_json:
        current_data = json.loads(current_data_json[0])
        current_data['status'] = status
        if admin_notes:
            current_data['admin_notes'] = admin_notes
        
        cursor.execute("UPDATE requests SET status=?, data=? WHERE request_id=?", 
                       (status, json.dumps(current_data), request_id))
        conn.commit()
    conn.close()


# --------------------------------- الدوال المساعدة ---------------------------------

async def reply_to_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None, parse_mode='HTML'):
    """دالة مساعدة لإرسال رسالة إلى المحادثة الحالية وحفظ معرفها وحذف الرسالة السابقة."""
    # لتنظيف المحادثة قبل إرسال رسالة جديدة.
    if context.user_data.get('last_bot_message_id'):
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['last_bot_message_id']
            )
        except Exception:
            pass # نتجاهل الأخطاء

    if update.callback_query:
        # إذا كان التحديث من زر، نستخدم edit_message_text لتجنب رسالة جديدة قدر الإمكان
        try:
            # نحاول التعديل أولاً (هو الأفضل لتجربة مستخدم سلسة)
            message = await update.callback_query.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        except Exception:
            # إذا فشل التعديل (مثل محاولة تعديل رسالة محذوفة أو رسالة /start)، نرسل رسالة جديدة
            try:
                await update.callback_query.message.delete()
            except Exception:
                pass
                
            message = await update.effective_chat.send_message(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
    else:
        message = await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )

    context.user_data['last_bot_message_id'] = message.message_id
    return message

def get_back_to_main_menu_keyboard():
    """إنشاء لوحة مفاتيح زر العودة للقائمة الرئيسية."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("↩️ العودة للقائمة الرئيسية", callback_data='to_main_menu')
    ]])

# --------------------------------- الدوال الأساسية ---------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """البداية - عرض القائمة الرئيسية أو بدء التسجيل."""
    
    query = update.callback_query
    if query:
        await query.answer()
        user = query.from_user
    else:
        user = update.effective_user
        # محاولة حذف رسالة /start
        if update.message and update.message.text and update.message.text.startswith('/start'):
            try:
                await context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
            except Exception:
                pass
            
    # تنظيف بيانات المستخدم ما عدا بيانات المشرف
    # تم تحديث القائمة لتشمل البيانات الهامة للمستخدم المسجل
    keys_to_keep = ['is_admin', 'user_id', 'full_name', 'first_name', 'last_name', 'team_name']
    for key in list(context.user_data.keys()):
        if key not in keys_to_keep:
            context.user_data.pop(key, None)
            
    
    user_data = get_db_user(user.id)
    if not user_data:
        # ** رسالة الترحيب المطلوبة (التسجيل)**
        context.user_data['user_id'] = user.id
        await reply_to_chat(update, context, 
                            f"أهليييين **بأبطال أبناء الأرض** 👋!\n\nأنا هون لساعدكم تقدموا طلب للHR.\n\n"
                            f"يبدو أنك لم تسجل بعد. الرجاء إدخال **اسمك الكامل** (الأول والأخير):", 
                            reply_markup=ReplyKeyboardRemove(),
                            parse_mode='Markdown')
        return FULL_NAME_REGISTRATION
    
    # تخزين بيانات المستخدم المسجل
    context.user_data.update(user_data)


    # إنشاء لوحة المفاتيح الرئيسية 
    keyboard = [
        [InlineKeyboardButton("📝 طلب اعتذار", callback_data='apology'),
         InlineKeyboardButton("🌴 طلب إجازة", callback_data='leave')],
        [InlineKeyboardButton("🛠️ قسم المشاكل", callback_data='problem'),
         InlineKeyboardButton("💡 اقتراحات وملاحظات", callback_data='feedback')],
        [InlineKeyboardButton("📚 مراجع الفريق", callback_data='references_menu'),
         InlineKeyboardButton("🎁 هدية لطيفة", callback_data='motivation')],
        # الزر الجديد المطلوب
        [InlineKeyboardButton("لا تنسى ذكر الله 📿", callback_data='dhikr')],
        # زر المطور المطلوب
        [InlineKeyboardButton(f"المطور: {DEVELOPER_USERNAME} 🧑‍💻", callback_data='developer_contact')]
    ]
    
    # إضافة زر المشرف إذا كان المستخدم مشرفاً
    if user.id in ADMIN_USER_IDS:
        keyboard.append([InlineKeyboardButton("لوحة تحكم المشرف ⚙️", callback_data='admin_menu_start')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    # ** رسالة الترحيب المطلوبة (القائمة الرئيسية)**
    text = f"""
أهليييين **بأبطال أبناء الأرض** 👋
أنا هون لساعدكم تقدموا طلب للHR. كيف يمكنني مساعدتك اليوم؟
"""

    await reply_to_chat(update, context, text, reply_markup=reply_markup, parse_mode='Markdown')
    return MAIN_MENU

async def get_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الأولى في التسجيل: حفظ الاسم الكامل."""
    full_name = update.message.text.strip()
    
    # التأكد من وجود نص
    if not full_name:
        await reply_to_chat(update, context, 
                            "الرجاء إدخال اسمك الكامل:",
                            reply_markup=ReplyKeyboardRemove())
        return FULL_NAME_REGISTRATION
        
    context.user_data['full_name'] = full_name
    
    # محاولة تقسيم الاسم إلى أول وأخير لتسجيله في DB (حيث أن الاسم الأول هو ما يتم استخدامه للترحيب)
    name_parts = full_name.split(' ', 1)
    context.user_data['first_name'] = name_parts[0]
    context.user_data['last_name'] = name_parts[1] if len(name_parts) > 1 else "" 
    
    welcome_text = f"تم تسجيل اسمك **{context.user_data['full_name']}**! 🎉"
    
    # إنشاء لوحة مفاتيح لاختيار الفريق
    keyboard_rows = [[]]
    for team in TEAM_OPTIONS:
        keyboard_rows[-1].append(InlineKeyboardButton(team, callback_data=f"team_{team}"))
        if len(keyboard_rows[-1]) == 2:
            keyboard_rows.append([])
    
    keyboard_rows.append([InlineKeyboardButton("↩️ إلغاء والعودة للقائمة", callback_data='to_main_menu')])
    
    reply_markup = InlineKeyboardMarkup(keyboard_rows)
    
    await reply_to_chat(update, context, 
                        f"{welcome_text}\n\nالآن، من فضلك اختر فريقك:", 
                        reply_markup=reply_markup,
                        parse_mode='Markdown')
    return TEAM_NAME_SELECTION

async def finalize_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الثانية والأخيرة في التسجيل: حفظ الفريق وتسجيل المستخدم."""
    query = update.callback_query
    await query.answer()
    
    team_name = query.data.replace('team_', '')
    
    user_id = context.user_data['user_id']
    full_name = context.user_data['full_name']
    first_name = context.user_data.get('first_name', '')
    last_name = context.user_data.get('last_name', '')
    
    register_db_user(user_id, full_name, first_name, last_name, team_name)
    context.user_data['team_name'] = team_name
    
    return await start(update, context) # العودة إلى القائمة الرئيسية


# --------------------------------- وظائف الإجازات والاعتذارات (نماذج) ---------------------------------

async def handle_leave_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """بدء طلب الإجازة: طلب تاريخ البدء."""
    await reply_to_chat(update, context, 
                        "حسناً، لتقديم طلب إجازة. من فضلك أدخل تاريخ بدء الإجازة (بصيغة **DD/MM/YYYY**):",
                        reply_markup=get_back_to_main_menu_keyboard(),
                        parse_mode='Markdown')
    return LEAVE_START_DATE

async def get_leave_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ تاريخ البدء وطلب تاريخ الانتهاء."""
    # ** يتم هنا تركيز بسيط على التحقق من صحة التاريخ كإجراء أفضل (نموذج)**
    date_str = update.message.text.strip()
    try:
        time.strptime(date_str, '%d/%m/%Y')
    except ValueError:
        await reply_to_chat(update, context, 
                            "⚠️ تنسيق التاريخ غير صحيح. الرجاء إدخال تاريخ بدء الإجازة بصيغة **DD/MM/YYYY**:",
                            reply_markup=get_back_to_main_menu_keyboard(),
                            parse_mode='Markdown')
        return LEAVE_START_DATE
        
    context.user_data['leave_start_date'] = date_str
    await reply_to_chat(update, context, 
                        "شكراً. الآن، أدخل تاريخ انتهاء الإجازة (بصيغة **DD/MM/YYYY**):",
                        reply_markup=get_back_to_main_menu_keyboard(),
                        parse_mode='Markdown')
    return LEAVE_END_DATE

async def get_leave_end_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ تاريخ الانتهاء وطلب سبب الإجازة."""
    date_str = update.message.text.strip()
    try:
        time.strptime(date_str, '%d/%m/%Y')
    except ValueError:
        await reply_to_chat(update, context, 
                            "⚠️ تنسيق التاريخ غير صحيح. الرجاء إدخال تاريخ انتهاء الإجازة بصيغة **DD/MM/YYYY**:",
                            reply_markup=get_back_to_main_menu_keyboard(),
                            parse_mode='Markdown')
        return LEAVE_END_DATE
        
    context.user_data['leave_end_date'] = date_str
    await reply_to_chat(update, context, 
                        "ما هو سبب الإجازة؟",
                        reply_markup=get_back_to_main_menu_keyboard())
    return LEAVE_REASON

async def get_leave_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ سبب الإجازة وطلب أي ملاحظات إضافية."""
    context.user_data['leave_reason'] = update.message.text.strip()
    await reply_to_chat(update, context, 
                        "هل لديك أي ملاحظات إضافية بخصوص الإجازة؟ (أو أرسل '**لا**'):",
                        reply_markup=get_back_to_main_menu_keyboard(),
                        parse_mode='Markdown')
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
    
    # حفظ الطلب في DB
    request_id = save_request(context.user_data['user_id'], 'Leave', data)
    
    # ------------------- إرسال إشعار للمشرف -------------------
    
    admin_text = f"""
🛑 طلب إجازة جديد (ID: **{request_id}**)

**المتطوع:** {context.user_data['full_name']}
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
    
    if ADMIN_CHAT_ID and ADMIN_CHAT_ID.isdigit():
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
    await reply_to_chat(update, context, "✅ تم إرسال طلب الإجازة بنجاح! سيتم إخطارك بالرد قريباً.\n\n")
    
    return await start(update, context) 


async def handle_apology_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """بدء طلب الاعتذار: طلب نوع الاعتذار."""
    await reply_to_chat(update, context, 
                        "لتقديم طلب اعتذار، من فضلك أدخل نوع الاعتذار (مثلاً: غياب، تأخير، عدم إكمال مهمة):",
                        reply_markup=get_back_to_main_menu_keyboard())
    return APOLOGY_TYPE

async def get_apology_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ نوع الاعتذار وطلب السبب."""
    context.user_data['apology_type'] = update.message.text.strip()
    await reply_to_chat(update, context, 
                        "ما هو سبب هذا الاعتذار؟",
                        reply_markup=get_back_to_main_menu_keyboard())
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
    
    # ** يمكن إضافة إشعار المشرف لطلب الاعتذار هنا **
    
    return await start(update, context) 

async def dhikr_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """إرسال رسالة الذكر المطلوبة."""
    query = update.callback_query
    await query.answer()
    
    await reply_to_chat(update, context, 
                        f"🕊️ **لا تنسى ذكر الله** 🕊️\n{DHIKR_MESSAGE}", 
                        reply_markup=get_back_to_main_menu_keyboard(),
                        parse_mode='Markdown')
    return MAIN_MENU

async def developer_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """إرسال رسالة المطور المطلوبة."""
    query = update.callback_query
    await query.answer()
    
    await reply_to_chat(update, context, 
                        f"🧑‍💻 تم تطوير هذا البوت بواسطة: **{DEVELOPER_USERNAME}**\n\n"
                        "نتمنى لكم تجربة استخدام ممتازة!", 
                        reply_markup=get_back_to_main_menu_keyboard(),
                        parse_mode='Markdown')
    return MAIN_MENU

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يُستخدم لمعالجة أزرار القائمة الرئيسية."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == 'leave':
        return await handle_leave_request(update, context)
    elif data == 'apology':
        return await handle_apology_request(update, context)
    elif data == 'dhikr':
        return await dhikr_reminder(update, context) 
    elif data == 'developer_contact':
        return await developer_contact(update, context) 
    elif data == 'problem':
        await reply_to_chat(update, context, 
                            "لإبلاغ عن مشكلة، من فضلك صفها بإيجاز:",
                            reply_markup=get_back_to_main_menu_keyboard())
        # ** تم تعديل العودة لتكون حالة مخصصة في المستقبل، لكن حالياً تبقى في MAIN_MENU **
        return MAIN_MENU 
    elif data == 'feedback':
        await reply_to_chat(update, context, 
                            "لإرسال اقتراح أو ملاحظة، اكتب رسالتك وسنقرأها بتمعن:",
                            reply_markup=get_back_to_main_menu_keyboard())
        # ** تم تعديل العودة لتكون حالة مخصصة في المستقبل، لكن حالياً تبقى في MAIN_MENU **
        return MAIN_MENU 
    elif data == 'references_menu':
        await handle_references_menu(update, context)
        return REFERENCES_MENU
    elif data == 'motivation':
        await reply_to_chat(update, context, "أنت تقوم بعمل رائع! شكراً لجهودك! 🌟", 
                            reply_markup=get_back_to_main_menu_keyboard()) # تم إضافة زر العودة
        return MAIN_MENU
    elif data == 'admin_menu_start':
        return await admin_menu(update, context) # ** معالجة زر المشرف **
    
    return MAIN_MENU

async def handle_references_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """إرسال ملف المراجع (PDF) للمستخدم."""
    query = update.callback_query
    if query:
        await query.answer()
        
    text = "إليك ملف المراجع الخاص بالفريق. يرجى الاطلاع عليه جيداً. 📄"
    
    # حذف رسالة البوت الأخيرة قبل إرسال الملف (لأن الملف لا يمكن تعديله)
    if context.user_data.get('last_bot_message_id'):
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['last_bot_message_id']
            )
            context.user_data['last_bot_message_id'] = None 
        except Exception:
            pass

    # يتم هنا افتراض وجود ملف مرجعي للمحاكاة، يجب استبدال هذا بالملف الحقيقي
    if os.path.exists(REFERENCE_GUIDE_PATH):
        try:
            with open(REFERENCE_GUIDE_PATH, 'rb') as doc_file:
                message = await context.bot.send_document(
                    chat_id=update.effective_chat.id, 
                    document=InputFile(doc_file, filename='دليل_المراجع.pdf'),
                    caption=text,
                    reply_markup=get_back_to_main_menu_keyboard()
                )
                context.user_data['last_bot_message_id'] = message.message_id
        except Exception as e:
             logger.error(f"فشل إرسال الملف: {e}")
             await update.effective_chat.send_message(
                 text=text + "\n\n❌ ملاحظة: فشل إرسال ملف المراجع (قد يكون خطأ في الملف).",
                 reply_markup=get_back_to_main_menu_keyboard()
             )
    else:
        # إرسال رسالة نصية في حال عدم وجود الملف
        message = await update.effective_chat.send_message( 
                            text=text + "\n\n❌ ملاحظة: لم يتم العثور على ملف المراجع (PDF) على السيرفر.",
                            reply_markup=get_back_to_main_menu_keyboard())
        context.user_data['last_bot_message_id'] = message.message_id


    return REFERENCES_MENU


# --------------------------------- وظائف الإدارة (Admin) ---------------------------------

async def is_admin(update: Update) -> bool:
    """التحقق مما إذا كان المستخدم مشرفاً."""
    if update.effective_user and update.effective_user.id in ADMIN_USER_IDS:
        return True
    return False

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """عرض لوحة تحكم المشرف."""
    if not await is_admin(update):
        if update.message:
            await update.message.reply_text("⛔ غير مصرح لك بالوصول إلى لوحة التحكم هذه.")
        return ConversationHandler.END

    context.user_data['is_admin'] = True
    
    if update.message:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        except Exception:
            pass
        
    keyboard = [
        [InlineKeyboardButton("✅ مراجعة الطلبات المعلقة (قريباً)", callback_data='admin_view_pending_temp')],
        [InlineKeyboardButton("👤 إدارة المتطوعين", callback_data='admin_manage_volunteers')],
        [InlineKeyboardButton("↩️ العودة لقائمة المستخدم", callback_data='to_main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # ** تم تعديل الدالة لاستخدام reply_to_chat لضمان التنظيف **
    await reply_to_chat(update, context, "لوحة تحكم المشرف 🛠️", reply_markup=reply_markup, parse_mode='Markdown')
    
    return ADMIN_MENU

async def manage_volunteers_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """بدء مسار إدارة المتطوعين."""
    query = update.callback_query
    await query.answer()

    if not await is_admin(update):
        await query.message.edit_text("⛔ غير مصرح لك بالقيام بهذا الإجراء.")
        return ADMIN_MENU
    
    keyboard = [
        [InlineKeyboardButton("➕ إضافة متطوع جديد (يدوياً)", callback_data='admin_add_volunteer')],
        [InlineKeyboardButton("🔙 العودة للقائمة الإدارية", callback_data='admin_menu_back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # ** تم تعديل الدالة لاستخدام reply_to_chat لضمان التنظيف **
    await reply_to_chat(update, context, "إدارة المتطوعين:", reply_markup=reply_markup)
    return ADMIN_MENU

async def start_add_volunteer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """طلب الاسم الكامل للمتطوع الجديد."""
    query = update.callback_query
    await query.answer()
    
    if not await is_admin(update):
        return ADMIN_MENU
        
    await reply_to_chat(update, context, 
                        "لإضافة متطوع يدوياً، يرجى إرسال **الاسم الكامل** للمتطوع (الأول والأخير):", 
                        reply_markup=get_back_to_main_menu_keyboard(),
                        parse_mode='Markdown')
    return ADD_VOLUNTEER_FULL_NAME

async def get_volunteer_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """حفظ الاسم الكامل وطلب تحديد الفريق."""
    full_name = update.message.text.strip()
    
    if not full_name:
        await reply_to_chat(update, context, 
                            "الرجاء إدخال الاسم الكامل للمتطوع.",
                            reply_markup=get_back_to_main_menu_keyboard())
        return ADD_VOLUNTEER_FULL_NAME
        
    context.user_data['temp_new_volunteer_name'] = full_name
    
    # إنشاء لوحة مفاتيح لاختيار الفريق (الفرق الجديدة)
    keyboard_rows = [[]]
    for team in TEAM_OPTIONS:
        keyboard_rows[-1].append(InlineKeyboardButton(team, callback_data=f"addvol_team_{team}"))
        if len(keyboard_rows[-1]) == 2:
            keyboard_rows.append([])
    
    keyboard_rows.append([InlineKeyboardButton("↩️ العودة للقائمة الرئيسية", callback_data='to_main_menu')])

    reply_markup = InlineKeyboardMarkup(keyboard_rows)
    
    await reply_to_chat(update, context, f"تم حفظ الاسم: **{full_name}**\nالآن، من فضلك اختر فريق المتطوع:", reply_markup=reply_markup, parse_mode='Markdown')
    return ADD_VOLUNTEER_SELECT_TEAM

async def finalize_add_volunteer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """تحديد الفريق والانتهاء من عملية الإضافة."""
    query = update.callback_query
    await query.answer()
    
    team_name = query.data.replace('addvol_team_', '')
    full_name = context.user_data.pop('temp_new_volunteer_name', 'متطوع غير معروف') # تنظيف المتغير المؤقت
    
    
    # محاولة تعديل رسالة الاختيار ثم إرسال رسالة التأكيد
    # تم استخدام reply_to_chat لضمان سلاسة التعديل أو إرسال رسالة جديدة
    await reply_to_chat(update, context, 
                        f"✅ تم تأكيد تسجيل المتطوع:\n"
                        f"**الاسم:** {full_name}\n"
                        f"**الفريق:** {team_name}\n\n"
                        "ملاحظة: المتطوع يحتاج إلى بدء المحادثة مع البوت ليتم تسجيله رسمياً في قاعدة البيانات.",
                        parse_mode='Markdown',
                        reply_markup=get_back_to_main_menu_keyboard())
                                  
    # العودة لحالة المشرف بانتظار زر العودة
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
        await query.message.edit_text(f"🛑 الطلب رقم **{request_id}** لم يعد معلقاً أو غير موجود.", parse_mode='Markdown')
        return

    # تحديث حالة الطلب في DB
    new_status = 'Approved' if action == 'approve' else 'Rejected'
    update_request_status(request_id, new_status)

    user_chat_id = request['data']['user_chat_id']
    
    # ------------------- تحديث رسالة المشرف -------------------
    
    admin_update_text = f"🛑 طلب {request_type} (ID: **{request_id}**)\n\n"
    admin_update_text += f"**المتطوع:** {request['full_name']}\n"
    admin_update_text += f"**الحالة:** {'✅ مقبول' if new_status == 'Approved' else '❌ مرفوض'}\n"
    admin_update_text += "\n--- تم الرد على هذا الطلب ---"
    
    try:
        await query.message.edit_text(admin_update_text, parse_mode='Markdown', reply_markup=None)
    except Exception as e:
        logger.error(f"فشل تحديث رسالة المشرف: {e}")

    # ------------------- إشعار للمتطوع -------------------
    
    user_notification_text = f"🚨 حالة طلبك: **{request_type}** (ID: **{request_id}**)\n\n"
    
    if new_status == 'Approved':
        user_notification_text += "✅ **تم قبول طلبك!**\n\n"
        if request_type == 'Leave':
             user_notification_text += "نتمنى لك وقتاً سعيداً! لا تغب كثيراً، سنشتاق لك ✨"
        else:
             user_notification_text += "يمكنك المتابعة."
    else: # Rejected
        user_notification_text += "❌ **تم رفض طلبك.** يرجى التواصل مع HR.\n"
        user_notification_text += f"للتواصل: {HR_CONTACT_INFO}"

    try:
        await context.bot.send_message(
            chat_id=user_chat_id,
            text=user_notification_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"فشل إرسال إشعار للمستخدم {request['user_id']}: {e}")


# --------------------------------- Fallback و Cancel ---------------------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دالة الإلغاء (يتم استدعاؤها عبر أمر /cancel)."""
    
    # تنظيف بيانات الجلسة 
    keys_to_keep = ['is_admin', 'user_id', 'full_name', 'first_name', 'last_name', 'team_name']
    for key in list(context.user_data.keys()):
        if key not in keys_to_keep:
            context.user_data.pop(key, None)
            
    # حذف رسالة /cancel
    if update.message:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        except Exception:
            pass

    await reply_to_chat(update, context, 
                        "❌ تم إلغاء العملية والعودة للقائمة الرئيسية.",
                        reply_markup=ReplyKeyboardRemove())
    
    return ConversationHandler.END

async def to_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دالة مساعدة لمعالجة زر العودة للقائمة الرئيسية أو الإدارية."""
    query = update.callback_query
    await query.answer()
    
    # تنظيف بيانات العملية الحالية عند العودة (تنظيف آمن)
    keys_to_keep = ['is_admin', 'user_id', 'full_name', 'first_name', 'last_name', 'team_name']
    for key in list(context.user_data.keys()):
        if key not in keys_to_keep:
            context.user_data.pop(key, None)
    
    if query.data == 'admin_menu_back':
        return await admin_menu(update, context)
    
    # العودة للقائمة الرئيسية (to_main_menu)
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
    
    # Handler الإجراءات الإدارية
    # تم تصحيح الـ pattern ليتوافق مع طريقة التسمية
    admin_action_handler = CallbackQueryHandler(handle_admin_action, pattern=r'^admin_(approve|reject)_[A-Za-z]+_\d+$', per_message=True)
    application.add_handler(admin_action_handler)
    
    # Handler الأوامر العامة (مثل /admin)
    application.add_handler(CommandHandler('admin', admin_menu))
    
    # ConversationHandler للمهام الرئيسية والإدارية
    conv_handler = ConversationHandler(
        # تم إضافة 'admin_menu_start' كنقطة دخول من القائمة الرئيسية
        entry_points=[CommandHandler('start', start),
                      CallbackQueryHandler(main_menu_handler, pattern='^(apology|leave|problem|feedback|motivation|references_menu|dhikr|developer_contact|admin_menu_start)$', per_message=True)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_handler, pattern='^(apology|leave|problem|feedback|motivation|references_menu|dhikr|developer_contact|admin_menu_start)$', per_message=True)
            ],
            
            # حالات التسجيل
            FULL_NAME_REGISTRATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_full_name)],
            TEAM_NAME_SELECTION: [
                CallbackQueryHandler(finalize_registration, pattern=r'^team_', per_message=True),
                CallbackQueryHandler(to_menu_handler, pattern='^to_main_menu$', per_message=True) 
            ],
            
            # حالات طلب الإجازة
            LEAVE_START_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_leave_start_date)],
            LEAVE_END_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_leave_end_date)],
            LEAVE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_leave_reason)],
            LEAVE_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_leave_request)],

            # حالات طلب الاعتذار
            APOLOGY_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_apology_type)],
            APOLOGY_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_apology_request)],
            
            # حالات قائمة المشرف وإضافة متطوعين
            ADMIN_MENU: [
                CallbackQueryHandler(manage_volunteers_menu, pattern='^admin_manage_volunteers$', per_message=True),
                CallbackQueryHandler(to_menu_handler, pattern='^to_main_menu$', per_message=True),
                CallbackQueryHandler(to_menu_handler, pattern='^admin_menu_back$', per_message=True),
                CallbackQueryHandler(lambda update, context: update.callback_query.answer("هذه الميزة ستكون متاحة قريباً!"), pattern='^admin_view_pending_temp$', per_message=True) # Placeholder
            ],
            ADD_VOLUNTEER_FULL_NAME: [
                # تمت إزالة CallbackQueryHandler هنا والاعتماد على Fallbacks
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_volunteer_full_name)
            ],
            ADD_VOLUNTEER_SELECT_TEAM: [
                CallbackQueryHandler(finalize_add_volunteer, pattern=r'^addvol_team_', per_message=True),
                CallbackQueryHandler(to_menu_handler, pattern='^to_main_menu$', per_message=True)
            ],
            
            # حالات المراجع
            REFERENCES_MENU: [CallbackQueryHandler(to_menu_handler, pattern='^to_main_menu$', per_message=True)]
        },
        fallbacks=[CommandHandler('cancel', cancel),
                   CallbackQueryHandler(to_menu_handler, pattern='^(to_main_menu|admin_menu_back)$', per_message=True)]
    )
    
    application.add_handler(conv_handler)
    
    # ** تم حذف حلقة الـ for الخاصة بـ CallbackQueryHandler group=1 لعدم فعاليتها**
    # ** والاعتماد على Fallbacks للتعامل مع أزرار العودة داخل حالات الـ TEXT **

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
        
    # إضافة هذا السطر لتجنب مشكلة 'webhooks' غير موجودة في بعض إعدادات PTB
    if hasattr(application, 'webhooks'):
        return application.webhooks(environ, start_response)
    else:
        status = '500 INTERNAL SERVER ERROR'
        headers = [('Content-type', 'text/plain')]
        start_response(status, headers)
        return [b"Application webhooks method not found."]

# --------------------------------- دالة التشغيل المحلية (للتطوير فقط) ---------------------------------
if __name__ == '__main__':
    if application:
        logger.info("يتم التشغيل محلياً باستخدام Polling. اضغط Ctrl+C للإيقاف.")
        # application.run_polling(poll_interval=1.0)
        pass # تم تعطيل التشغيل الفعلي في الكود للحفاظ على نموذج الـ WSGI
