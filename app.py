# -*- coding: utf-8 -*-
import os
import hmac
import hashlib
import json
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy import func

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'teacher-booking-secret-2026')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///teacher_booking.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

CORS(app)
db = SQLAlchemy(app)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '')

# ─────────────────────────────────────────────
# 資料模型
# ─────────────────────────────────────────────

class Teacher(db.Model):
    """老師資料"""
    __tablename__ = 'teachers'
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(50), nullable=False)
    title       = db.Column(db.String(100))  # 頭銜（例：資深講師、認證教練）
    specialty   = db.Column(db.String(200))  # 專長
    bio         = db.Column(db.Text)  # 簡介
    hourly_rate = db.Column(db.Integer, default=1000)  # 時薪
    is_active   = db.Column(db.Boolean, default=True)
    photo_url   = db.Column(db.String(500))  # 照片 URL
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'title': self.title,
            'specialty': self.specialty,
            'bio': self.bio,
            'hourly_rate': self.hourly_rate,
            'is_active': self.is_active,
            'photo_url': self.photo_url
        }


class TimeSlot(db.Model):
    """可預約時段"""
    __tablename__ = 'time_slots'
    id         = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'))
    date       = db.Column(db.String(10), nullable=False)  # YYYY-MM-DD
    time       = db.Column(db.String(5), nullable=False)   # HH:MM
    duration   = db.Column(db.Integer, default=60)  # 分鐘
    is_booked  = db.Column(db.Boolean, default=False)
    
    teacher = db.relationship('Teacher', backref='slots')


class Booking(db.Model):
    """預約記錄"""
    __tablename__ = 'bookings'
    id              = db.Column(db.Integer, primary_key=True)
    booking_number  = db.Column(db.String(20), unique=True)
    teacher_id      = db.Column(db.Integer, db.ForeignKey('teachers.id'))
    customer_name   = db.Column(db.String(50), nullable=False)
    customer_phone  = db.Column(db.String(20), nullable=False)
    line_user_id    = db.Column(db.String(100))
    date            = db.Column(db.String(10), nullable=False)
    time            = db.Column(db.String(5), nullable=False)
    duration        = db.Column(db.Integer, default=60)
    total_price     = db.Column(db.Integer, default=0)
    status          = db.Column(db.String(20), default='confirmed')  # confirmed, cancelled, completed
    source          = db.Column(db.String(20), default='web')  # web, line
    note            = db.Column(db.Text)
    created_at      = db.Column(db.DateTime, default=datetime.now)
    
    teacher = db.relationship('Teacher', backref='bookings')
    
    def to_dict(self):
        return {
            'id': self.id,
            'booking_number': self.booking_number,
            'teacher_id': self.teacher_id,
            'teacher_name': self.teacher.name if self.teacher else '',
            'customer_name': self.customer_name,
            'customer_phone': self.customer_phone,
            'date': self.date,
            'time': self.time,
            'duration': self.duration,
            'total_price': self.total_price,
            'status': self.status,
            'source': self.source,
            'note': self.note,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        }


class Customer(db.Model):
    """客戶資料"""
    __tablename__ = 'customers'
    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(50), nullable=False)
    phone           = db.Column(db.String(20), unique=True)
    line_user_id    = db.Column(db.String(100), unique=True)
    email           = db.Column(db.String(100))
    total_bookings  = db.Column(db.Integer, default=0)
    total_hours     = db.Column(db.Integer, default=0)
    total_spent     = db.Column(db.Integer, default=0)
    created_at      = db.Column(db.DateTime, default=datetime.now)


class AIConversation(db.Model):
    """AI 對話記錄"""
    __tablename__ = 'ai_conversations'
    id              = db.Column(db.Integer, primary_key=True)
    line_user_id    = db.Column(db.String(100), nullable=False)
    user_message    = db.Column(db.Text, nullable=False)
    ai_response     = db.Column(db.Text, nullable=False)
    intent          = db.Column(db.String(50))  # booking, query, cancel
    booking_id      = db.Column(db.Integer, db.ForeignKey('bookings.id'))
    created_at      = db.Column(db.DateTime, default=datetime.now)


# ─────────────────────────────────────────────
# 輔助函式
# ─────────────────────────────────────────────

def check_admin():
    """驗證管理員權限"""
    pw = request.headers.get('X-Admin-Password')
    if not pw or pw != ADMIN_PASSWORD:
        return jsonify({'error': 'Unauthorized'}), 401
    return None


def generate_booking_number():
    """生成預約編號"""
    today = datetime.now().strftime('%Y%m%d')
    count = Booking.query.filter(Booking.booking_number.like(f'BK{today}%')).count()
    return f'BK{today}{str(count + 1).zfill(4)}'


def parse_booking_message(message):
    """
    解析 LINE 訊息，提取預約資訊
    支援格式：
    - 我要預約陳老師 2/20 15:00
    - 預約 王老師 2月20日 下午3點
    """
    import re
    
    result = {
        'is_booking': False,
        'teacher_name': None,
        'date': None,
        'time': None
    }
    
    # 檢查預約意圖
    booking_keywords = ['預約', '訂', '約', '想要', '我要']
    if not any(keyword in message for keyword in booking_keywords):
        return result
    
    result['is_booking'] = True
    
    # 解析老師名字（假設格式：X老師 或 直接名字）
    teacher_pattern = r'([一-龥]{2,4}(?:老師)?)'
    teacher_match = re.search(teacher_pattern, message)
    if teacher_match:
        teacher_name = teacher_match.group(1).replace('老師', '')
        result['teacher_name'] = teacher_name
    
    # 解析日期
    date_patterns = [
        r'(\d{1,2})[/月-](\d{1,2})',
        r'(\d{4})[/月-](\d{1,2})[/日-](\d{1,2})'
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, message)
        if match:
            if len(match.groups()) == 2:
                month, day = match.groups()
                year = datetime.now().year
            else:
                year, month, day = match.groups()
            result['date'] = f'{year}-{int(month):02d}-{int(day):02d}'
            break
    
    # 解析時間
    time_patterns = [
        r'(\d{1,2}):(\d{2})',
        r'(\d{1,2})\s*點',
        r'下午(\d{1,2})點?',
        r'上午(\d{1,2})點?',
    ]
    
    for pattern in time_patterns:
        match = re.search(pattern, message)
        if match:
            if '下午' in pattern:
                hour = int(match.group(1))
                hour = hour + 12 if hour < 12 else hour
                result['time'] = f'{hour:02d}:00'
            elif '上午' in pattern:
                hour = int(match.group(1))
                result['time'] = f'{hour:02d}:00'
            elif ':' in pattern:
                result['time'] = f'{int(match.group(1)):02d}:{match.group(2)}'
            else:
                result['time'] = f'{int(match.group(1)):02d}:00'
            break
    
    return result


def find_teacher_by_name(name):
    """根據名字查找老師"""
    return Teacher.query.filter(
        Teacher.name.like(f'%{name}%'),
        Teacher.is_active == True
    ).first()


def check_availability(teacher_id, date, time):
    """檢查時段是否可預約"""
    # 檢查是否已被預約
    existing = Booking.query.filter(
        Booking.teacher_id == teacher_id,
        Booking.date == date,
        Booking.time == time,
        Booking.status == 'confirmed'
    ).first()
    
    return existing is None


def send_line_message(user_id, message):
    """發送 LINE 訊息"""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return False
    
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    data = {
        'to': user_id,
        'messages': [{'type': 'text', 'text': message}]
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        return response.status_code == 200
    except:
        return False


def send_admin_notification(message):
    """發送通知給管理員"""
    print(f'管理員通知: {message}')
    return True


# ─────────────────────────────────────────────
# 公開 API
# ─────────────────────────────────────────────

@app.route('/')
def index():
    """學生預約頁面"""
    return send_from_directory('static', 'index.html')


@app.route('/api/teachers')
def get_teachers():
    """取得所有老師"""
    teachers = Teacher.query.filter_by(is_active=True).all()
    return jsonify([t.to_dict() for t in teachers])


@app.route('/api/teachers/<int:teacher_id>/availability')
def check_teacher_availability(teacher_id):
    """檢查老師可用時段"""
    date = request.args.get('date')
    
    if not date:
        return jsonify({'error': 'Missing date'}), 400
    
    # 取得該日期已預約的時段
    booked = Booking.query.filter(
        Booking.teacher_id == teacher_id,
        Booking.date == date,
        Booking.status == 'confirmed'
    ).all()
    
    booked_times = [b.time for b in booked]
    
    # 預設可預約時段
    all_times = [f'{h:02d}:00' for h in range(9, 21)]  # 09:00 - 20:00
    available_times = [t for t in all_times if t not in booked_times]
    
    return jsonify({
        'available_times': available_times,
        'booked_times': booked_times
    })


@app.route('/api/book', methods=['POST'])
def create_booking():
    """建立預約（網頁）"""
    data = request.get_json()
    
    teacher = Teacher.query.get(data['teacher_id'])
    if not teacher:
        return jsonify({'error': 'Teacher not found'}), 404
    
    # 檢查可用性
    if not check_availability(teacher.id, data['date'], data['time']):
        return jsonify({'error': '此時段已被預約'}), 400
    
    # 計算費用
    duration = data.get('duration', 60)
    total_price = int((duration / 60) * teacher.hourly_rate)
    
    # 建立預約
    booking = Booking(
        booking_number=generate_booking_number(),
        teacher_id=teacher.id,
        customer_name=data['name'],
        customer_phone=data['phone'],
        date=data['date'],
        time=data['time'],
        duration=duration,
        total_price=total_price,
        source='web',
        note=data.get('note', '')
    )
    
    db.session.add(booking)
    db.session.commit()
    
    # 更新客戶資料
    customer = Customer.query.filter_by(phone=data['phone']).first()
    if not customer:
        customer = Customer(
            name=data['name'],
            phone=data['phone']
        )
        db.session.add(customer)
    
    customer.total_bookings += 1
    customer.total_hours += duration
    customer.total_spent += total_price
    db.session.commit()
    
    return jsonify({
        'success': True,
        'booking': booking.to_dict()
    }), 201


# ─────────────────────────────────────────────
# LINE Webhook（AI 自動預約）
# ─────────────────────────────────────────────

@app.route('/webhook/line', methods=['POST'])
def line_webhook():
    """LINE Webhook - AI 自動預約"""
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    # 驗證簽章
    if LINE_CHANNEL_SECRET:
        hash_value = hmac.new(
            LINE_CHANNEL_SECRET.encode('utf-8'),
            body.encode('utf-8'),
            hashlib.sha256
        ).digest()
        expected_signature = hash_value.hex()
        
        if signature != expected_signature:
            return 'Invalid signature', 403
    
    try:
        events = json.loads(body).get('events', [])
    except:
        return 'OK', 200
    
    for event in events:
        if event['type'] != 'message' or event['message']['type'] != 'text':
            continue
        
        user_id = event['source']['userId']
        message = event['message']['text']
        
        # 解析訊息
        parsed = parse_booking_message(message)
        
        if not parsed['is_booking']:
            reply = handle_general_query(message, user_id)
        else:
            reply = handle_booking_request(parsed, user_id, message)
        
        # 回覆訊息
        send_line_message(user_id, reply)
    
    return 'OK', 200


def handle_general_query(message, user_id):
    """處理一般查詢"""
    # 查詢預約
    if '查詢' in message or '我的預約' in message:
        bookings = Booking.query.filter_by(
            line_user_id=user_id,
            status='confirmed'
        ).order_by(Booking.date, Booking.time).all()
        
        if not bookings:
            return '您目前沒有預約記錄。'
        
        reply = '您的預約記錄：\n\n'
        for b in bookings:
            reply += f'{b.booking_number}\n{b.teacher.name} 老師\n{b.date} {b.time}\n費用：{b.total_price}元\n\n'
        
        return reply
    
    # 老師列表
    if '老師' in message and ('有哪些' in message or '名單' in message):
        teachers = Teacher.query.filter_by(is_active=True).all()
        reply = '目前可預約的老師：\n\n'
        for t in teachers:
            reply += f'{t.name} 老師\n{t.title}\n專長：{t.specialty}\n\n'
        return reply
    
    # 預設回覆
    return '您好！\n\n可用指令：\n1. 預約 老師名字 日期 時間\n   例：預約 陳老師 2/20 15:00\n\n2. 查詢預約\n\n3. 老師名單'


def handle_booking_request(parsed, user_id, original_message):
    """處理預約請求"""
    # 驗證必要資訊
    if not parsed['teacher_name']:
        return '請提供老師名字，例如：預約 陳老師 2/20 15:00'
    
    if not parsed['date']:
        return '請提供預約日期，例如：2/20 或 2月20日'
    
    if not parsed['time']:
        return '請提供預約時間，例如：15:00 或 下午3點'
    
    # 驗證日期
    try:
        booking_date = datetime.strptime(parsed['date'], '%Y-%m-%d')
        if booking_date.date() < datetime.now().date():
            return '無法預約過去的日期。'
    except:
        return '日期格式錯誤。'
    
    # 尋找老師
    teacher = find_teacher_by_name(parsed['teacher_name'])
    if not teacher:
        return f'找不到「{parsed["teacher_name"]}」老師。\n\n請傳送「老師名單」查看可預約的老師。'
    
    # 檢查可用性
    if not check_availability(teacher.id, parsed['date'], parsed['time']):
        return f'{teacher.name} 老師在 {parsed["date"]} {parsed["time"]} 已被預約。\n\n請選擇其他時間或傳送「查詢可用時段」。'
    
    # 取得客戶資料
    customer = Customer.query.filter_by(line_user_id=user_id).first()
    
    if not customer:
        return f'已為您保留 {teacher.name} 老師的時段！\n\n請提供您的姓名和電話以完成預約：\n確認預約 張三 0912345678'
    
    # 建立預約
    duration = 60
    total_price = int((duration / 60) * teacher.hourly_rate)
    
    booking = Booking(
        booking_number=generate_booking_number(),
        teacher_id=teacher.id,
        customer_name=customer.name,
        customer_phone=customer.phone,
        line_user_id=user_id,
        date=parsed['date'],
        time=parsed['time'],
        duration=duration,
        total_price=total_price,
        source='line'
    )
    
    db.session.add(booking)
    
    # 更新客戶統計
    customer.total_bookings += 1
    customer.total_hours += duration
    customer.total_spent += total_price
    
    db.session.commit()
    
    # 記錄 AI 對話
    conversation = AIConversation(
        line_user_id=user_id,
        user_message=original_message,
        ai_response='預約成功',
        intent='booking',
        booking_id=booking.id
    )
    db.session.add(conversation)
    db.session.commit()
    
    # 發送通知給管理員
    admin_msg = f'新預約通知\n\n預約編號：{booking.booking_number}\n客戶：{customer.name}\n老師：{teacher.name}\n時間：{parsed["date"]} {parsed["time"]}\n來源：LINE AI'
    send_admin_notification(admin_msg)
    
    # 回覆客戶
    return f'預約成功！\n\n預約編號：{booking.booking_number}\n老師：{teacher.name}\n時間：{parsed["date"]} {parsed["time"]}\n課程時長：{duration}分鐘\n費用：{total_price}元\n\n請準時出席，期待您的到來！'


# ─────────────────────────────────────────────
# 管理後台 API
# ─────────────────────────────────────────────

@app.route('/admin')
def admin_login():
    """管理員登入頁"""
    return send_from_directory('static', 'admin_login.html')


@app.route('/admin/api/login', methods=['POST'])
def admin_login_api():
    """管理員登入 API"""
    data = request.get_json()
    if data.get('password') == ADMIN_PASSWORD:
        session['admin'] = True
        return jsonify({'success': True})
    return jsonify({'error': 'Invalid password'}), 401


@app.route('/dashboard')
def dashboard():
    """管理後台首頁"""
    return send_from_directory('static', 'admin_dashboard.html')


@app.route('/admin/api/bookings', methods=['GET'])
def admin_get_bookings():
    err = check_admin()
    if err: return err
    
    date = request.args.get('date')
    status = request.args.get('status')
    
    query = Booking.query
    if date:
        query = query.filter_by(date=date)
    if status:
        query = query.filter_by(status=status)
    
    bookings = query.order_by(Booking.created_at.desc()).all()
    return jsonify([b.to_dict() for b in bookings])


@app.route('/admin/api/bookings/<int:bid>/cancel', methods=['POST'])
def admin_cancel_booking(bid):
    err = check_admin()
    if err: return err
    
    booking = Booking.query.get_or_404(bid)
    booking.status = 'cancelled'
    db.session.commit()
    
    if booking.line_user_id:
        msg = f'您的預約已取消\n\n預約編號：{booking.booking_number}\n老師：{booking.teacher.name}\n時間：{booking.date} {booking.time}'
        send_line_message(booking.line_user_id, msg)
    
    return jsonify({'success': True})


@app.route('/admin/api/teachers', methods=['GET'])
def admin_get_teachers():
    err = check_admin()
    if err: return err
    
    teachers = Teacher.query.all()
    return jsonify([t.to_dict() for t in teachers])


@app.route('/admin/api/teachers', methods=['POST'])
def admin_add_teacher():
    err = check_admin()
    if err: return err
    
    data = request.get_json()
    teacher = Teacher(
        name=data['name'],
        title=data.get('title', ''),
        specialty=data.get('specialty', ''),
        bio=data.get('bio', ''),
        hourly_rate=data.get('hourly_rate', 1000),
        is_active=True
    )
    db.session.add(teacher)
    db.session.commit()
    
    return jsonify(teacher.to_dict()), 201


@app.route('/admin/api/customers', methods=['GET'])
def admin_get_customers():
    err = check_admin()
    if err: return err
    
    customers = Customer.query.order_by(Customer.total_spent.desc()).all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'phone': c.phone,
        'email': c.email,
        'total_bookings': c.total_bookings,
        'total_hours': c.total_hours,
        'total_spent': c.total_spent,
        'created_at': c.created_at.strftime('%Y-%m-%d') if c.created_at else ''
    } for c in customers])


@app.route('/admin/api/stats', methods=['GET'])
def admin_get_stats():
    err = check_admin()
    if err: return err
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    stats = {
        'total_bookings': Booking.query.filter_by(status='confirmed').count(),
        'today_bookings': Booking.query.filter_by(date=today, status='confirmed').count(),
        'total_customers': Customer.query.count(),
        'total_revenue': db.session.query(func.sum(Booking.total_price)).filter_by(status='confirmed').scalar() or 0,
        'line_bookings': Booking.query.filter_by(source='line', status='confirmed').count(),
        'ai_conversations': AIConversation.query.count()
    }
    
    return jsonify(stats)


@app.route('/admin/api/ai-conversations', methods=['GET'])
def admin_get_ai_conversations():
    err = check_admin()
    if err: return err
    
    conversations = AIConversation.query.order_by(AIConversation.created_at.desc()).limit(100).all()
    
    return jsonify([{
        'id': c.id,
        'line_user_id': c.line_user_id,
        'user_message': c.user_message,
        'ai_response': c.ai_response,
        'intent': c.intent,
        'booking_id': c.booking_id,
        'created_at': c.created_at.strftime('%Y-%m-%d %H:%M') if c.created_at else ''
    } for c in conversations])


# ─────────────────────────────────────────────
# 初始化範例資料
# ─────────────────────────────────────────────

def seed():
    """建立範例資料"""
    if Teacher.query.count() > 0:
        return
    
    teachers_data = [
        {
            'name': '陳志豪',
            'title': '資深講師',
            'specialty': '數位行銷、社群經營、品牌策略',
            'bio': '10年業界經驗，曾任知名企業行銷總監',
            'hourly_rate': 1500
        },
        {
            'name': '林美慧',
            'title': '專業顧問',
            'specialty': '職涯規劃、履歷優化、面試技巧',
            'bio': '人資背景，協助超過500位求職者成功轉職',
            'hourly_rate': 1200
        },
        {
            'name': '王俊傑',
            'title': '技術專家',
            'specialty': 'Python、資料分析、機器學習',
            'bio': '科技業資深工程師，豐富教學經驗',
            'hourly_rate': 1800
        },
        {
            'name': '張雅婷',
            'title': '語言教師',
            'specialty': '英語教學、多益、商業英文',
            'bio': '英國留學歸國，TESOL認證教師',
            'hourly_rate': 1000
        }
    ]
    
    for data in teachers_data:
        db.session.add(Teacher(**data))
    
    db.session.commit()
    print('範例老師資料建立完成')


# ─────────────────────────────────────────────
# 應用程式初始化
# ─────────────────────────────────────────────

with app.app_context():
    try:
        db.create_all()
        print('資料庫初始化完成')
        if Teacher.query.count() == 0:
            seed()
    except Exception as e:
        print(f'資料庫初始化錯誤: {e}')


# ─────────────────────────────────────────────
# 啟動
# ─────────────────────────────────────────────

if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    with app.app_context():
        db.create_all()
        seed()
    print('\n  老師預約系統')
    print('  學生預約頁面：http://localhost:5000')
    print('  管理後台登入：http://localhost:5000/admin')
    print(f'  管理密碼：    {ADMIN_PASSWORD}')
    print(f'  LINE Webhook: http://your-domain.com/webhook/line\n')
    app.run(debug=True, port=5000)