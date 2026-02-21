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
app.secret_key = os.environ.get('SECRET_KEY', 'studyroom-secret-2026')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///studyroom.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

CORS(app)
db = SQLAlchemy(app)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '')

# ─────────────────────────────────────────────
# 資料模型
# ─────────────────────────────────────────────

class Room(db.Model):
    """座位/包廂"""
    __tablename__ = 'rooms'
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(50), nullable=False)  # 座位A1, 包廂1
    type        = db.Column(db.String(20), nullable=False)  # single(單人), double(雙人), group(小包廂), vip(大包廂)
    capacity    = db.Column(db.Integer, default=1)          # 可容納人數
    hourly_rate = db.Column(db.Integer, default=50)         # 每小時費用
    description = db.Column(db.Text)                        # 說明（插座/WiFi等）
    is_active   = db.Column(db.Boolean, default=True)       # 是否開放
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'capacity': self.capacity,
            'hourly_rate': self.hourly_rate,
            'description': self.description,
            'is_active': self.is_active
        }


class TimeSlot(db.Model):
    """可預約時段"""
    __tablename__ = 'time_slots'
    id      = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'))
    date    = db.Column(db.String(10), nullable=False)  # YYYY-MM-DD
    start   = db.Column(db.String(5), nullable=False)   # HH:MM
    end     = db.Column(db.String(5), nullable=False)   # HH:MM
    status  = db.Column(db.String(20), default='available')  # available, booked, locked
    
    room = db.relationship('Room', backref='slots')


class Booking(db.Model):
    """預約記錄"""
    __tablename__ = 'bookings'
    id              = db.Column(db.Integer, primary_key=True)
    booking_number  = db.Column(db.String(20), unique=True)  # 預約編號
    room_id         = db.Column(db.Integer, db.ForeignKey('rooms.id'))
    customer_name   = db.Column(db.String(50), nullable=False)
    customer_phone  = db.Column(db.String(20), nullable=False)
    line_user_id    = db.Column(db.String(100))  # LINE User ID（如果是從LINE預約）
    date            = db.Column(db.String(10), nullable=False)
    start_time      = db.Column(db.String(5), nullable=False)
    end_time        = db.Column(db.String(5), nullable=False)
    hours           = db.Column(db.Integer, default=1)
    total_price     = db.Column(db.Integer, default=0)
    status          = db.Column(db.String(20), default='confirmed')  # confirmed, cancelled, completed
    source          = db.Column(db.String(20), default='web')  # web, line
    note            = db.Column(db.Text)
    created_at      = db.Column(db.DateTime, default=datetime.now)
    
    room = db.relationship('Room', backref='bookings')
    
    def to_dict(self):
        return {
            'id': self.id,
            'booking_number': self.booking_number,
            'room_id': self.room_id,
            'room_name': self.room.name if self.room else '',
            'room_type': self.room.type if self.room else '',
            'customer_name': self.customer_name,
            'customer_phone': self.customer_phone,
            'date': self.date,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'hours': self.hours,
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
    is_vip          = db.Column(db.Boolean, default=False)
    created_at      = db.Column(db.DateTime, default=datetime.now)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'total_bookings': self.total_bookings,
            'total_hours': self.total_hours,
            'total_spent': self.total_spent,
            'is_vip': self.is_vip
        }


class AIConversation(db.Model):
    """AI 對話記錄"""
    __tablename__ = 'ai_conversations'
    id              = db.Column(db.Integer, primary_key=True)
    line_user_id    = db.Column(db.String(100), nullable=False)
    user_message    = db.Column(db.Text, nullable=False)
    ai_response     = db.Column(db.Text, nullable=False)
    intent          = db.Column(db.String(50))  # booking, query, cancel, other
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


def calculate_hours(start_time, end_time):
    """計算時數"""
    start = datetime.strptime(start_time, '%H:%M')
    end = datetime.strptime(end_time, '%H:%M')
    duration = (end - start).total_seconds() / 3600
    return int(duration) if duration == int(duration) else duration


def parse_booking_message(message):
    """
    解析 LINE 訊息，提取預約資訊
    支援格式範例：
    - 我要預約2/20 15:00-17:00 單人座位
    - 預約 2月20日 下午3點到5點 包廂
    - 想訂 2/20 3pm-5pm A區座位
    """
    import re
    
    result = {
        'is_booking': False,
        'date': None,
        'start_time': None,
        'end_time': None,
        'room_type': None,
        'room_name': None
    }
    
    # 檢查是否為預約意圖
    booking_keywords = ['預約', '訂', '約', '想要', '我要']
    if not any(keyword in message for keyword in booking_keywords):
        return result
    
    result['is_booking'] = True
    
    # 解析日期
    # 格式: 2/20, 2月20日, 02/20, 2-20
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
    # 格式: 15:00-17:00, 3pm-5pm, 下午3點到5點
    time_patterns = [
        r'(\d{1,2}):(\d{2})\s*[-到至]\s*(\d{1,2}):(\d{2})',
        r'(\d{1,2})\s*pm\s*[-到至]\s*(\d{1,2})\s*pm',
        r'下午(\d{1,2})點\s*到\s*(\d{1,2})點',
        r'(\d{1,2})點\s*[-到至]\s*(\d{1,2})點'
    ]
    
    for pattern in time_patterns:
        match = re.search(pattern, message)
        if match:
            groups = match.groups()
            if len(groups) == 4:
                result['start_time'] = f'{int(groups[0]):02d}:{int(groups[1]):02d}'
                result['end_time'] = f'{int(groups[2]):02d}:{int(groups[3]):02d}'
            elif 'pm' in pattern:
                start_hour = int(groups[0]) + 12 if int(groups[0]) < 12 else int(groups[0])
                end_hour = int(groups[1]) + 12 if int(groups[1]) < 12 else int(groups[1])
                result['start_time'] = f'{start_hour:02d}:00'
                result['end_time'] = f'{end_hour:02d}:00'
            else:
                result['start_time'] = f'{int(groups[0]):02d}:00'
                result['end_time'] = f'{int(groups[1]):02d}:00'
            break
    
    # 解析座位類型
    if '單人' in message or '一人' in message:
        result['room_type'] = 'single'
    elif '雙人' in message or '兩人' in message or '2人' in message:
        result['room_type'] = 'double'
    elif '小包廂' in message or '小間' in message:
        result['room_type'] = 'group'
    elif '大包廂' in message or 'VIP' in message or '大間' in message:
        result['room_type'] = 'vip'
    
    # 解析座位名稱
    room_name_pattern = r'([A-Z]\d+|包廂\d+|座位[A-Z]\d+)'
    match = re.search(room_name_pattern, message)
    if match:
        result['room_name'] = match.group(1)
    
    return result


def find_available_room(room_type, date, start_time, end_time, room_name=None):
    """尋找可用座位"""
    query = Room.query.filter_by(is_active=True)
    
    if room_name:
        query = query.filter_by(name=room_name)
    elif room_type:
        query = query.filter_by(type=room_type)
    
    rooms = query.all()
    
    for room in rooms:
        # 檢查是否有衝突的預約
        conflicts = Booking.query.filter(
            Booking.room_id == room.id,
            Booking.date == date,
            Booking.status == 'confirmed',
            db.or_(
                db.and_(Booking.start_time <= start_time, Booking.end_time > start_time),
                db.and_(Booking.start_time < end_time, Booking.end_time >= end_time),
                db.and_(Booking.start_time >= start_time, Booking.end_time <= end_time)
            )
        ).first()
        
        if not conflicts:
            return room
    
    return None


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
    """發送通知給管理員（可擴充為多種通知方式）"""
    # 這裡可以發送到特定的 LINE 群組、Email 等
    # 目前先記錄在資料庫
    print(f'管理員通知: {message}')
    return True


# ─────────────────────────────────────────────
# 公開 API
# ─────────────────────────────────────────────

@app.route('/')
def index():
    """學生預約頁面"""
    return send_from_directory('static', 'studyroom_booking.html')


@app.route('/api/rooms')
def get_rooms():
    """取得所有座位"""
    rooms = Room.query.filter_by(is_active=True).all()
    return jsonify([r.to_dict() for r in rooms])


@app.route('/api/rooms/<int:room_id>/availability')
def check_availability(room_id):
    """檢查座位可用性"""
    date = request.args.get('date')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    
    if not all([date, start_time, end_time]):
        return jsonify({'error': 'Missing parameters'}), 400
    
    conflicts = Booking.query.filter(
        Booking.room_id == room_id,
        Booking.date == date,
        Booking.status == 'confirmed',
        db.or_(
            db.and_(Booking.start_time <= start_time, Booking.end_time > start_time),
            db.and_(Booking.start_time < end_time, Booking.end_time >= end_time),
            db.and_(Booking.start_time >= start_time, Booking.end_time <= end_time)
        )
    ).first()
    
    return jsonify({'available': conflicts is None})


@app.route('/api/book', methods=['POST'])
def create_booking():
    """建立預約（網頁）"""
    data = request.get_json()
    
    room = Room.query.get(data['room_id'])
    if not room:
        return jsonify({'error': 'Room not found'}), 404
    
    # 檢查可用性
    available_room = find_available_room(
        None, 
        data['date'], 
        data['start_time'], 
        data['end_time'],
        room.name
    )
    
    if not available_room:
        return jsonify({'error': '此時段已被預約'}), 400
    
    # 計算費用
    hours = calculate_hours(data['start_time'], data['end_time'])
    total_price = int(hours * room.hourly_rate)
    
    # 建立預約
    booking = Booking(
        booking_number=generate_booking_number(),
        room_id=room.id,
        customer_name=data['name'],
        customer_phone=data['phone'],
        date=data['date'],
        start_time=data['start_time'],
        end_time=data['end_time'],
        hours=hours,
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
    customer.total_hours += hours
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
            # 非預約訊息，回覆使用說明
            reply = handle_general_query(message, user_id)
        else:
            # 預約訊息，自動處理
            reply = handle_booking_request(parsed, user_id, message)
        
        # 回覆訊息
        send_line_message(user_id, reply)
    
    return 'OK', 200


def handle_general_query(message, user_id):
    """處理一般查詢"""
    # 營業時間
    if '營業時間' in message or '幾點' in message or '開門' in message:
        return '我們的營業時間是每天 08:00 - 23:00。\n\n如需預約，請傳送：\n預約 日期 時間 座位類型\n\n例如：預約 2/20 15:00-17:00 單人座位'
    
    # 價格
    if '價格' in message or '多少錢' in message or '費用' in message:
        return '座位收費標準：\n單人座位：50元/小時\n雙人座位：80元/小時\n小包廂（4人）：150元/小時\nVIP包廂（6人）：250元/小時'
    
    # 查詢預約
    if '查詢' in message or '我的預約' in message:
        bookings = Booking.query.filter_by(
            line_user_id=user_id,
            status='confirmed'
        ).order_by(Booking.date, Booking.start_time).all()
        
        if not bookings:
            return '您目前沒有預約記錄。'
        
        reply = '您的預約記錄：\n\n'
        for b in bookings:
            reply += f'{b.booking_number}\n{b.room.name}\n{b.date} {b.start_time}-{b.end_time}\n費用：{b.total_price}元\n\n'
        
        return reply
    
    # 取消預約
    if '取消' in message:
        return '如需取消預約，請提供預約編號，例如：\n取消 BK202602200001'
    
    # 預設回覆
    return '您好，歡迎使用 K書中心預約系統！\n\n可用指令：\n1. 預約 2/20 15:00-17:00 單人座位\n2. 查詢預約\n3. 取消 預約編號\n4. 營業時間\n5. 價格'


def handle_booking_request(parsed, user_id, original_message):
    """處理預約請求"""
    # 驗證必要資訊
    if not parsed['date']:
        return '請提供預約日期，例如：2/20 或 2月20日'
    
    if not parsed['start_time'] or not parsed['end_time']:
        return '請提供預約時間，例如：15:00-17:00 或 下午3點到5點'
    
    # 驗證日期（不能預約過去的日期）
    booking_date = datetime.strptime(parsed['date'], '%Y-%m-%d')
    if booking_date.date() < datetime.now().date():
        return '無法預約過去的日期，請選擇今天或之後的日期。'
    
    # 尋找可用座位
    room = find_available_room(
        parsed['room_type'],
        parsed['date'],
        parsed['start_time'],
        parsed['end_time'],
        parsed['room_name']
    )
    
    if not room:
        # 沒有可用座位，提供替代方案
        alternative = suggest_alternative(
            parsed['room_type'],
            parsed['date'],
            parsed['start_time'],
            parsed['end_time']
        )
        
        if alternative:
            return f'抱歉，您選擇的座位在此時段已被預約。\n\n建議替代方案：\n{alternative}'
        else:
            return '抱歉，此時段沒有可用座位。請選擇其他時段或聯絡我們。'
    
    # 取得客戶資料
    customer = Customer.query.filter_by(line_user_id=user_id).first()
    
    if not customer:
        # 新客戶，需要提供電話
        return f'已為您保留 {room.name}！\n\n請提供您的姓名和電話以完成預約：\n確認預約 張三 0912345678'
    
    # 建立預約
    hours = calculate_hours(parsed['start_time'], parsed['end_time'])
    total_price = int(hours * room.hourly_rate)
    
    booking = Booking(
        booking_number=generate_booking_number(),
        room_id=room.id,
        customer_name=customer.name,
        customer_phone=customer.phone,
        line_user_id=user_id,
        date=parsed['date'],
        start_time=parsed['start_time'],
        end_time=parsed['end_time'],
        hours=hours,
        total_price=total_price,
        source='line'
    )
    
    db.session.add(booking)
    
    # 更新客戶統計
    customer.total_bookings += 1
    customer.total_hours += hours
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
    admin_msg = f'新預約通知\n\n預約編號：{booking.booking_number}\n客戶：{customer.name}\n座位：{room.name}\n時間：{parsed["date"]} {parsed["start_time"]}-{parsed["end_time"]}\n來源：LINE AI'
    send_admin_notification(admin_msg)
    
    # 回覆客戶
    return f'預約成功！\n\n預約編號：{booking.booking_number}\n座位：{room.name}\n時間：{parsed["date"]} {parsed["start_time"]}-{parsed["end_time"]}\n時數：{hours}小時\n費用：{total_price}元\n\n請準時到達，期待您的光臨！'


def suggest_alternative(room_type, date, start_time, end_time):
    """建議替代方案"""
    # 尋找同類型的其他座位
    rooms = Room.query.filter_by(type=room_type, is_active=True).all()
    
    for room in rooms:
        conflicts = Booking.query.filter(
            Booking.room_id == room.id,
            Booking.date == date,
            Booking.status == 'confirmed',
            db.or_(
                db.and_(Booking.start_time <= start_time, Booking.end_time > start_time),
                db.and_(Booking.start_time < end_time, Booking.end_time >= end_time)
            )
        ).first()
        
        if not conflicts:
            return f'{room.name} 目前可預約'
    
    # 沒有同類型的，建議其他類型
    other_rooms = Room.query.filter(Room.type != room_type, Room.is_active == True).all()
    for room in other_rooms:
        conflicts = Booking.query.filter(
            Booking.room_id == room.id,
            Booking.date == date,
            Booking.status == 'confirmed'
        ).first()
        
        if not conflicts:
            type_name = {'single': '單人', 'double': '雙人', 'group': '小包廂', 'vip': 'VIP包廂'}.get(room.type, room.type)
            return f'{room.name}（{type_name}）目前可預約'
    
    return None


# ─────────────────────────────────────────────
# 管理後台 API
# ─────────────────────────────────────────────

@app.route('/admin')
def admin_login():
    return send_from_directory('static', 'admin.html')


@app.route('/admin/api/login', methods=['POST'])
def admin_login_api():
    data = request.get_json()
    if data.get('password') == ADMIN_PASSWORD:
        session['admin'] = True
        return jsonify({'success': True})
    return jsonify({'error': 'Invalid password'}), 401


@app.route('/dashboard')
def dashboard():
    return send_from_directory('static', 'index.html')


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
    
    # 通知客戶
    if booking.line_user_id:
        msg = f'您的預約已取消\n\n預約編號：{booking.booking_number}\n座位：{booking.room.name}\n時間：{booking.date} {booking.start_time}-{booking.end_time}'
        send_line_message(booking.line_user_id, msg)
    
    return jsonify({'success': True})


@app.route('/admin/api/rooms', methods=['GET'])
def admin_get_rooms():
    err = check_admin()
    if err: return err
    
    rooms = Room.query.all()
    return jsonify([r.to_dict() for r in rooms])


@app.route('/admin/api/rooms', methods=['POST'])
def admin_add_room():
    err = check_admin()
    if err: return err
    
    data = request.get_json()
    room = Room(
        name=data['name'],
        type=data['type'],
        capacity=data.get('capacity', 1),
        hourly_rate=data.get('hourly_rate', 50),
        description=data.get('description', ''),
        is_active=True
    )
    db.session.add(room)
    db.session.commit()
    
    return jsonify(room.to_dict()), 201


@app.route('/admin/api/customers', methods=['GET'])
def admin_get_customers():
    err = check_admin()
    if err: return err
    
    customers = Customer.query.order_by(Customer.total_spent.desc()).all()
    return jsonify([c.to_dict() for c in customers])


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


# ─────────────────────────────────────────────
# 初始化範例資料
# ─────────────────────────────────────────────

def seed():
    """建立範例資料"""
    if Room.query.count() > 0:
        return
    
    # 建立座位
    rooms_data = [
        # 單人座位
        {'name': 'A1', 'type': 'single', 'capacity': 1, 'hourly_rate': 50, 'description': '靠窗座位，獨立插座，優質WiFi'},
        {'name': 'A2', 'type': 'single', 'capacity': 1, 'hourly_rate': 50, 'description': '安靜角落，獨立插座，優質WiFi'},
        {'name': 'A3', 'type': 'single', 'capacity': 1, 'hourly_rate': 50, 'description': '明亮位置，獨立插座，優質WiFi'},
        # 雙人座位
        {'name': 'B1', 'type': 'double', 'capacity': 2, 'hourly_rate': 80, 'description': '雙人桌，2個插座，適合討論'},
        {'name': 'B2', 'type': 'double', 'capacity': 2, 'hourly_rate': 80, 'description': '雙人桌，2個插座，適合討論'},
        # 小包廂
        {'name': '包廂1', 'type': 'group', 'capacity': 4, 'hourly_rate': 150, 'description': '4人包廂，獨立空間，白板，投影設備'},
        {'name': '包廂2', 'type': 'group', 'capacity': 4, 'hourly_rate': 150, 'description': '4人包廂，獨立空間，白板，投影設備'},
        # VIP包廂
        {'name': 'VIP1', 'type': 'vip', 'capacity': 6, 'hourly_rate': 250, 'description': '6人VIP包廂，會議桌，投影設備，冷氣獨立控制'},
    ]
    
    for data in rooms_data:
        db.session.add(Room(**data))
    
    db.session.commit()
    print('範例座位建立完成')


# ─────────────────────────────────────────────
# 應用程式初始化
# ─────────────────────────────────────────────

with app.app_context():
    try:
        db.create_all()
        print('資料庫初始化完成')
        if Room.query.count() == 0:
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
    print('\n  K書中心預約系統')
    print('  學生預約頁面：http://localhost:5000')
    print('  管理後台登入：http://localhost:5000/admin')
    print(f'  管理密碼：    {ADMIN_PASSWORD}')
    print(f'  LINE Webhook: http://your-domain.com/webhook/line\n')
    app.run(debug=True, port=5000)