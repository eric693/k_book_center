# -*- coding: utf-8 -*-
import os
import hmac
import hashlib
import json
import base64
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
    __tablename__ = 'teachers'
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(50), nullable=False)
    title       = db.Column(db.String(100))
    specialty   = db.Column(db.String(200))
    bio         = db.Column(db.Text)
    hourly_rate = db.Column(db.Integer, default=1000)
    is_active   = db.Column(db.Boolean, default=True)
    photo_url   = db.Column(db.String(500))

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
    __tablename__ = 'time_slots'
    id         = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'))
    date       = db.Column(db.String(10), nullable=False)
    time       = db.Column(db.String(5), nullable=False)
    duration   = db.Column(db.Integer, default=60)
    is_booked  = db.Column(db.Boolean, default=False)
    teacher    = db.relationship('Teacher', backref='slots')


class Booking(db.Model):
    __tablename__ = 'bookings'
    id             = db.Column(db.Integer, primary_key=True)
    booking_number = db.Column(db.String(20), unique=True)
    teacher_id     = db.Column(db.Integer, db.ForeignKey('teachers.id'))
    customer_name  = db.Column(db.String(50), nullable=False)
    customer_phone = db.Column(db.String(20), nullable=False)
    line_user_id   = db.Column(db.String(100))
    date           = db.Column(db.String(10), nullable=False)
    time           = db.Column(db.String(5), nullable=False)
    duration       = db.Column(db.Integer, default=60)
    total_price    = db.Column(db.Integer, default=0)
    status         = db.Column(db.String(20), default='confirmed')
    source         = db.Column(db.String(20), default='web')
    note           = db.Column(db.Text)
    created_at     = db.Column(db.DateTime, default=datetime.now)
    teacher        = db.relationship('Teacher', backref='bookings')

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
    __tablename__ = 'customers'
    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(50), nullable=False)
    phone          = db.Column(db.String(20), unique=True)
    line_user_id   = db.Column(db.String(100), unique=True)
    email          = db.Column(db.String(100))
    total_bookings = db.Column(db.Integer, default=0)
    total_hours    = db.Column(db.Integer, default=0)
    total_spent    = db.Column(db.Integer, default=0)
    created_at     = db.Column(db.DateTime, default=datetime.now)

    # 暫存預約流程狀態（可改用 Redis）
    pending_teacher_id = db.Column(db.Integer)
    pending_date       = db.Column(db.String(10))


class AIConversation(db.Model):
    __tablename__ = 'ai_conversations'
    id           = db.Column(db.Integer, primary_key=True)
    line_user_id = db.Column(db.String(100), nullable=False)
    user_message = db.Column(db.Text, nullable=False)
    ai_response  = db.Column(db.Text, nullable=False)
    intent       = db.Column(db.String(50))
    booking_id   = db.Column(db.Integer, db.ForeignKey('bookings.id'))
    created_at   = db.Column(db.DateTime, default=datetime.now)


# ─────────────────────────────────────────────
# 輔助函式
# ─────────────────────────────────────────────

def check_admin():
    pw = request.headers.get('X-Admin-Password')
    if not pw or pw != ADMIN_PASSWORD:
        return jsonify({'error': 'Unauthorized'}), 401
    return None


def generate_booking_number():
    today = datetime.now().strftime('%Y%m%d')
    count = Booking.query.filter(Booking.booking_number.like(f'BK{today}%')).count()
    return f'BK{today}{str(count + 1).zfill(4)}'


def find_teacher_by_name(name):
    return Teacher.query.filter(
        Teacher.name.like(f'%{name}%'),
        Teacher.is_active == True
    ).first()


def check_availability(teacher_id, date, time):
    existing = Booking.query.filter(
        Booking.teacher_id == teacher_id,
        Booking.date == date,
        Booking.time == time,
        Booking.status == 'confirmed'
    ).first()
    return existing is None


def get_available_times(teacher_id, date):
    booked = Booking.query.filter(
        Booking.teacher_id == teacher_id,
        Booking.date == date,
        Booking.status == 'confirmed'
    ).all()
    booked_times = {b.time for b in booked}
    all_times = [f'{h:02d}:00' for h in range(9, 21)]
    return [t for t in all_times if t not in booked_times]


def get_or_create_customer(user_id, name=None, phone=None):
    customer = Customer.query.filter_by(line_user_id=user_id).first()
    if not customer and name and phone:
        customer = Customer(name=name, phone=phone, line_user_id=user_id)
        db.session.add(customer)
        db.session.commit()
    return customer


def send_flex_message(user_id, alt_text, flex_content):
    """Push Flex Message"""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return False
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    data = {
        'to': user_id,
        'messages': [{
            'type': 'flex',
            'altText': alt_text,
            'contents': flex_content
        }]
    }
    try:
        r = requests.post(url, headers=headers, json=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f'Push Flex 失敗: {e}')
        return False


def reply_flex_message(reply_token, alt_text, flex_content):
    """Reply Flex Message"""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return False
    url = 'https://api.line.me/v2/bot/message/reply'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    data = {
        'replyToken': reply_token,
        'messages': [{
            'type': 'flex',
            'altText': alt_text,
            'contents': flex_content
        }]
    }
    try:
        r = requests.post(url, headers=headers, json=data, timeout=10)
        if r.status_code != 200:
            print(f'Reply Flex 失敗: {r.status_code} {r.text}')
        return r.status_code == 200
    except Exception as e:
        print(f'Reply Flex 失敗: {e}')
        return False


def reply_text_message(reply_token, text):
    """Reply 純文字（備用）"""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return False
    url = 'https://api.line.me/v2/bot/message/reply'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    data = {
        'replyToken': reply_token,
        'messages': [{'type': 'text', 'text': text}]
    }
    try:
        r = requests.post(url, headers=headers, json=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f'Reply Text 失敗: {e}')
        return False


def send_text_message(user_id, text):
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return False
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    data = {'to': user_id, 'messages': [{'type': 'text', 'text': text}]}
    try:
        r = requests.post(url, headers=headers, json=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f'Push Text 失敗: {e}')
        return False


def send_admin_notification(message):
    print(f'管理員通知: {message}')
    return True


# ─────────────────────────────────────────────
# Flex Message 模板
# ─────────────────────────────────────────────

def build_welcome_flex():
    """歡迎選單"""
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "📚 K書中心", "weight": "bold",
                 "size": "xl", "color": "#ffffff"},
                {"type": "text", "text": "請選擇您需要的服務", "size": "sm",
                 "color": "#ffffff99"}
            ],
            "backgroundColor": "#4A90E2",
            "paddingAll": "20px"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#4A90E2",
                    "action": {
                        "type": "message",
                        "label": "📋 查看老師名單",
                        "text": "老師名單"
                    },
                    "height": "sm"
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "message",
                        "label": "📅 查詢我的預約",
                        "text": "查詢預約"
                    },
                    "height": "sm"
                }
            ]
        }
    }


def build_teacher_carousel(teachers):
    """老師列表 Carousel"""
    bubbles = []
    for t in teachers:
        # 專長截短
        specialty_short = (t.specialty or '')[:30] + ('...' if len(t.specialty or '') > 30 else '')

        bubble = {
            "type": "bubble",
            "size": "kilo",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": t.name + " 老師",
                        "weight": "bold",
                        "size": "lg",
                        "color": "#ffffff"
                    },
                    {
                        "type": "text",
                        "text": t.title or "",
                        "size": "sm",
                        "color": "#ffffff99"
                    }
                ],
                "backgroundColor": "#4A90E2",
                "paddingAll": "15px"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "box",
                        "layout": "baseline",
                        "spacing": "sm",
                        "contents": [
                            {"type": "text", "text": "專長", "color": "#aaaaaa",
                             "size": "sm", "flex": 1},
                            {"type": "text", "text": specialty_short,
                             "wrap": True, "color": "#666666", "size": "sm", "flex": 4}
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "baseline",
                        "spacing": "sm",
                        "contents": [
                            {"type": "text", "text": "時薪", "color": "#aaaaaa",
                             "size": "sm", "flex": 1},
                            {"type": "text", "text": f"${t.hourly_rate}/hr",
                             "color": "#E05A2B", "size": "sm", "flex": 4, "weight": "bold"}
                        ]
                    }
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#4A90E2",
                        "height": "sm",
                        "action": {
                            "type": "postback",
                            "label": "選擇此老師",
                            "data": f"action=select_teacher&teacher_id={t.id}&teacher_name={t.name}",
                            "displayText": f"我想預約 {t.name} 老師"
                        }
                    }
                ]
            }
        }
        bubbles.append(bubble)

    return {
        "type": "carousel",
        "contents": bubbles
    }


def build_date_picker_flex(teacher_id, teacher_name):
    """日期選擇（提供未來7天按鈕）"""
    today = datetime.now().date()
    date_buttons = []

    for i in range(1, 8):
        d = today + timedelta(days=i)
        label = d.strftime('%m/%d') + (' (明天)' if i == 1 else '')
        weekday = ['一', '二', '三', '四', '五', '六', '日'][d.weekday()]
        date_buttons.append({
            "type": "button",
            "style": "secondary",
            "height": "sm",
            "action": {
                "type": "postback",
                "label": f"{d.strftime('%m/%d')} (週{weekday})",
                "data": f"action=select_date&teacher_id={teacher_id}&date={d.strftime('%Y-%m-%d')}",
                "displayText": f"選擇 {d.strftime('%Y-%m-%d')}"
            }
        })

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"預約 {teacher_name} 老師",
                 "weight": "bold", "size": "lg", "color": "#ffffff"},
                {"type": "text", "text": "請選擇上課日期",
                 "size": "sm", "color": "#ffffff99"}
            ],
            "backgroundColor": "#27AE60",
            "paddingAll": "15px"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": date_buttons
        }
    }


def build_time_picker_flex(teacher_id, teacher_name, date, available_times):
    """時段選擇"""
    if not available_times:
        return {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "😢 此日期已無可用時段",
                     "weight": "bold", "size": "md"},
                    {"type": "text", "text": "請返回選擇其他日期",
                     "color": "#888888", "size": "sm", "margin": "md"}
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [{
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "postback",
                        "label": "← 重新選擇日期",
                        "data": f"action=select_teacher&teacher_id={teacher_id}&teacher_name={teacher_name}",
                        "displayText": f"重新選擇日期"
                    }
                }]
            }
        }

    # 每行顯示3個時段
    time_rows = []
    row = []
    for i, t in enumerate(available_times):
        row.append({
            "type": "button",
            "style": "secondary",
            "height": "sm",
            "flex": 1,
            "action": {
                "type": "postback",
                "label": t,
                "data": f"action=select_time&teacher_id={teacher_id}&date={date}&time={t}",
                "displayText": f"選擇 {t}"
            }
        })
        if len(row) == 3 or i == len(available_times) - 1:
            # 補空格讓最後一行對齊
            while len(row) < 3:
                row.append({"type": "filler"})
            time_rows.append({
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "contents": row
            })
            row = []

    d_fmt = datetime.strptime(date, '%Y-%m-%d').strftime('%m月%d日')

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"預約 {teacher_name} 老師",
                 "weight": "bold", "size": "lg", "color": "#ffffff"},
                {"type": "text", "text": f"📅 {d_fmt}　請選擇時段",
                 "size": "sm", "color": "#ffffff99"}
            ],
            "backgroundColor": "#27AE60",
            "paddingAll": "15px"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": time_rows
        }
    }


def build_confirm_flex(teacher_name, date, time, price, teacher_id):
    """預約確認卡片"""
    d_fmt = datetime.strptime(date, '%Y-%m-%d').strftime('%Y年%m月%d日')
    weekday = ['一', '二', '三', '四', '五', '六', '日'][
        datetime.strptime(date, '%Y-%m-%d').weekday()
    ]
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "確認預約資訊",
                 "weight": "bold", "size": "xl", "color": "#ffffff"},
            ],
            "backgroundColor": "#E67E22",
            "paddingAll": "15px"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                _info_row("👨‍🏫 老師", f"{teacher_name} 老師"),
                _info_row("📅 日期", f"{d_fmt} (週{weekday})"),
                _info_row("🕐 時間", time),
                _info_row("⏱ 時長", "60 分鐘"),
                _info_row("💰 費用", f"$ {price} 元"),
                {
                    "type": "separator",
                    "margin": "md"
                },
                {
                    "type": "text",
                    "text": "確認後將完成預約，請準時出席。",
                    "size": "xs",
                    "color": "#888888",
                    "wrap": True,
                    "margin": "md"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "secondary",
                    "flex": 1,
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "← 返回",
                        "data": f"action=select_date&teacher_id={teacher_id}&date={date}",
                        "displayText": "重新選擇時段"
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#27AE60",
                    "flex": 2,
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "✅ 確認預約",
                        "data": f"action=confirm_booking&teacher_id={teacher_id}&date={date}&time={time}",
                        "displayText": f"確認預約 {teacher_name} 老師 {date} {time}"
                    }
                }
            ]
        }
    }


def build_booking_success_flex(booking):
    """預約成功卡片"""
    teacher_name = booking.teacher.name if booking.teacher else ''
    d_fmt = datetime.strptime(booking.date, '%Y-%m-%d').strftime('%Y年%m月%d日')
    weekday = ['一', '二', '三', '四', '五', '六', '日'][
        datetime.strptime(booking.date, '%Y-%m-%d').weekday()
    ]
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🎉 預約成功！",
                 "weight": "bold", "size": "xl", "color": "#ffffff"},
                {"type": "text", "text": booking.booking_number,
                 "size": "sm", "color": "#ffffff99"}
            ],
            "backgroundColor": "#27AE60",
            "paddingAll": "15px"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                _info_row("👨‍🏫 老師", f"{teacher_name} 老師"),
                _info_row("📅 日期", f"{d_fmt} (週{weekday})"),
                _info_row("🕐 時間", booking.time),
                _info_row("⏱ 時長", f"{booking.duration} 分鐘"),
                _info_row("💰 費用", f"$ {booking.total_price} 元"),
                {
                    "type": "separator",
                    "margin": "md"
                },
                {
                    "type": "text",
                    "text": "請準時出席，期待您的到來！",
                    "size": "sm",
                    "color": "#27AE60",
                    "wrap": True,
                    "margin": "md",
                    "weight": "bold"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [{
                "type": "button",
                "style": "secondary",
                "height": "sm",
                "action": {
                    "type": "message",
                    "label": "查詢我的預約",
                    "text": "查詢預約"
                }
            }]
        }
    }


def build_my_bookings_flex(bookings):
    """我的預約列表"""
    if not bookings:
        return {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "📅 尚無預約記錄",
                     "weight": "bold", "size": "md"},
                    {"type": "text", "text": "點下方按鈕開始預約課程",
                     "color": "#888888", "size": "sm", "margin": "md"}
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [{
                    "type": "button",
                    "style": "primary",
                    "color": "#4A90E2",
                    "action": {
                        "type": "message",
                        "label": "查看老師名單",
                        "text": "老師名單"
                    }
                }]
            }
        }

    bubbles = []
    for b in bookings:
        teacher_name = b.teacher.name if b.teacher else '未知'
        d_fmt = datetime.strptime(b.date, '%Y-%m-%d').strftime('%m/%d')
        bubble = {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {"type": "text", "text": b.booking_number,
                     "color": "#888888", "size": "xs"},
                    {"type": "text", "text": f"{teacher_name} 老師",
                     "weight": "bold", "size": "md"},
                    {"type": "text", "text": f"📅 {d_fmt}  🕐 {b.time}",
                     "size": "sm", "color": "#555555"},
                    {"type": "text", "text": f"💰 ${b.total_price} 元",
                     "size": "sm", "color": "#E05A2B"}
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [{
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "color": "#FF4444",
                    "action": {
                        "type": "postback",
                        "label": "取消預約",
                        "data": f"action=cancel_booking&booking_id={b.id}",
                        "displayText": f"取消預約 {b.booking_number}"
                    }
                }]
            }
        }
        bubbles.append(bubble)

    if len(bubbles) == 1:
        return bubbles[0]

    return {"type": "carousel", "contents": bubbles}


def build_register_flex(teacher_id, date, time):
    """要求使用者提供姓名電話"""
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "📝 完成註冊", "weight": "bold",
                 "size": "xl", "color": "#ffffff"},
                {"type": "text", "text": "首次預約，請提供基本資料",
                 "size": "sm", "color": "#ffffff99"}
            ],
            "backgroundColor": "#8E44AD",
            "paddingAll": "15px"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": "請回覆以下格式：\n\n註冊 姓名 手機號碼\n\n範例：\n註冊 張小明 0912345678",
                    "wrap": True,
                    "size": "sm",
                    "color": "#555555"
                }
            ]
        }
    }


def _info_row(label, value):
    """通用資訊行"""
    return {
        "type": "box",
        "layout": "baseline",
        "spacing": "sm",
        "contents": [
            {"type": "text", "text": label, "color": "#888888",
             "size": "sm", "flex": 3},
            {"type": "text", "text": value, "wrap": True,
             "color": "#333333", "size": "sm", "flex": 5, "weight": "bold"}
        ]
    }


# ─────────────────────────────────────────────
# LINE Webhook
# ─────────────────────────────────────────────

@app.route('/webhook/line', methods=['POST'])
def line_webhook():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    if LINE_CHANNEL_SECRET:
        hash_value = hmac.new(
            LINE_CHANNEL_SECRET.encode('utf-8'),
            body.encode('utf-8'),
            hashlib.sha256
        ).digest()
        expected_signature = base64.b64encode(hash_value).decode('utf-8')
        if signature != expected_signature:
            print('LINE 簽章驗證失敗')
            return 'Invalid signature', 403

    try:
        payload = json.loads(body) if body else {}
        events = payload.get('events', [])
    except Exception as e:
        print(f'JSON 解析失敗: {e}')
        return 'OK', 200

    if not events:
        return 'OK', 200

    for event in events:
        try:
            reply_token = event.get('replyToken')
            user_id = event.get('source', {}).get('userId')
            if not user_id:
                continue

            event_type = event.get('type')

            # ── 文字訊息 ──
            if event_type == 'message' and event.get('message', {}).get('type') == 'text':
                text = event['message']['text'].strip()
                handle_text_event(reply_token, user_id, text)

            # ── Postback（按鈕點擊）──
            elif event_type == 'postback':
                data = event.get('postback', {}).get('data', '')
                handle_postback_event(reply_token, user_id, data)

            # ── 加入好友 ──
            elif event_type == 'follow':
                flex = build_welcome_flex()
                reply_flex_message(reply_token, '歡迎使用 K書中心預約系統', flex)

        except Exception as e:
            print(f'處理 event 失敗: {e}')
            import traceback; traceback.print_exc()

    return 'OK', 200


def handle_text_event(reply_token, user_id, text):
    """處理文字訊息"""

    # 老師名單
    if '老師名單' in text or '老師列表' in text:
        teachers = Teacher.query.filter_by(is_active=True).all()
        flex = build_teacher_carousel(teachers)
        reply_flex_message(reply_token, f'目前有 {len(teachers)} 位老師可預約', flex)
        return

    # 查詢預約
    if '查詢' in text or '我的預約' in text:
        bookings = Booking.query.filter_by(
            line_user_id=user_id, status='confirmed'
        ).order_by(Booking.date, Booking.time).all()
        flex = build_my_bookings_flex(bookings)
        reply_flex_message(reply_token, f'您有 {len(bookings)} 筆預約', flex)
        return

    # 註冊：「註冊 姓名 電話」
    if text.startswith('註冊'):
        parts = text.split()
        if len(parts) >= 3:
            name = parts[1]
            phone = parts[2]
            existing = Customer.query.filter_by(phone=phone).first()
            if existing:
                existing.line_user_id = user_id
                db.session.commit()
                customer = existing
            else:
                customer = Customer(name=name, phone=phone, line_user_id=user_id)
                db.session.add(customer)
                db.session.commit()
            reply_text_message(reply_token, f'✅ 歡迎 {name}！已完成註冊，請繼續選擇預約時間。')
        else:
            reply_text_message(reply_token, '格式錯誤，請使用：\n註冊 姓名 手機號碼\n例：註冊 張小明 0912345678')
        return

    # 其他：顯示選單
    flex = build_welcome_flex()
    reply_flex_message(reply_token, 'K書中心預約系統', flex)


def handle_postback_event(reply_token, user_id, data):
    """處理 Postback（按鈕點擊）"""
    params = dict(p.split('=', 1) for p in data.split('&') if '=' in p)
    action = params.get('action', '')

    # 1. 選擇老師 → 顯示日期選擇
    if action == 'select_teacher':
        teacher_id = int(params.get('teacher_id', 0))
        teacher = Teacher.query.get(teacher_id)
        if not teacher:
            reply_text_message(reply_token, '老師不存在，請重新選擇。')
            return
        flex = build_date_picker_flex(teacher.id, teacher.name)
        reply_flex_message(reply_token, f'選擇預約日期 - {teacher.name} 老師', flex)

    # 2. 選擇日期 → 顯示時段
    elif action == 'select_date':
        teacher_id = int(params.get('teacher_id', 0))
        date = params.get('date', '')
        teacher = Teacher.query.get(teacher_id)
        if not teacher or not date:
            reply_text_message(reply_token, '參數錯誤，請重新選擇。')
            return
        available = get_available_times(teacher_id, date)
        flex = build_time_picker_flex(teacher_id, teacher.name, date, available)
        reply_flex_message(reply_token, f'{date} 可用時段', flex)

    # 3. 選擇時段 → 顯示確認畫面
    elif action == 'select_time':
        teacher_id = int(params.get('teacher_id', 0))
        date = params.get('date', '')
        time = params.get('time', '')
        teacher = Teacher.query.get(teacher_id)
        if not teacher:
            reply_text_message(reply_token, '老師不存在。')
            return
        price = teacher.hourly_rate
        flex = build_confirm_flex(teacher.name, date, time, price, teacher_id)
        reply_flex_message(reply_token, '確認預約資訊', flex)

    # 4. 確認預約 → 完成
    elif action == 'confirm_booking':
        teacher_id = int(params.get('teacher_id', 0))
        date = params.get('date', '')
        time = params.get('time', '')
        teacher = Teacher.query.get(teacher_id)

        if not teacher:
            reply_text_message(reply_token, '老師不存在。')
            return

        if not check_availability(teacher_id, date, time):
            reply_text_message(reply_token, f'⚠️ 很抱歉，{date} {time} 已被預約，請重新選擇時段。')
            return

        customer = Customer.query.filter_by(line_user_id=user_id).first()
        if not customer:
            # 未登記，先導向註冊
            flex = build_register_flex(teacher_id, date, time)
            reply_flex_message(reply_token, '請先完成註冊', flex)
            return

        duration = 60
        total_price = int((duration / 60) * teacher.hourly_rate)

        booking = Booking(
            booking_number=generate_booking_number(),
            teacher_id=teacher.id,
            customer_name=customer.name,
            customer_phone=customer.phone,
            line_user_id=user_id,
            date=date,
            time=time,
            duration=duration,
            total_price=total_price,
            source='line'
        )
        db.session.add(booking)
        customer.total_bookings += 1
        customer.total_hours += duration
        customer.total_spent += total_price
        db.session.commit()

        conv = AIConversation(
            line_user_id=user_id,
            user_message=f'Postback confirm: teacher={teacher_id} date={date} time={time}',
            ai_response='預約成功',
            intent='booking',
            booking_id=booking.id
        )
        db.session.add(conv)
        db.session.commit()

        send_admin_notification(
            f'新預約！{booking.booking_number} | {customer.name} | {teacher.name} | {date} {time}'
        )

        flex = build_booking_success_flex(booking)
        reply_flex_message(reply_token, f'預約成功！{booking.booking_number}', flex)

    # 5. 取消預約
    elif action == 'cancel_booking':
        booking_id = int(params.get('booking_id', 0))
        booking = Booking.query.get(booking_id)
        if not booking or booking.line_user_id != user_id:
            reply_text_message(reply_token, '找不到此預約或您無權取消。')
            return
        booking.status = 'cancelled'
        db.session.commit()
        reply_text_message(
            reply_token,
            f'✅ 已取消預約 {booking.booking_number}\n{booking.teacher.name} 老師 {booking.date} {booking.time}'
        )

    else:
        reply_text_message(reply_token, '未知操作，請重新選擇。')


# ─────────────────────────────────────────────
# 公開 API（Web 端不變）
# ─────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


@app.route('/api/teachers')
def get_teachers():
    teachers = Teacher.query.filter_by(is_active=True).all()
    return jsonify([t.to_dict() for t in teachers])


@app.route('/api/teachers/<int:teacher_id>/availability')
def check_teacher_availability(teacher_id):
    date = request.args.get('date')
    if not date:
        return jsonify({'error': 'Missing date'}), 400
    booked = Booking.query.filter(
        Booking.teacher_id == teacher_id,
        Booking.date == date,
        Booking.status == 'confirmed'
    ).all()
    booked_times = [b.time for b in booked]
    all_times = [f'{h:02d}:00' for h in range(9, 21)]
    available_times = [t for t in all_times if t not in booked_times]
    return jsonify({'available_times': available_times, 'booked_times': booked_times})


@app.route('/api/book', methods=['POST'])
def create_booking():
    data = request.get_json()
    teacher = Teacher.query.get(data['teacher_id'])
    if not teacher:
        return jsonify({'error': 'Teacher not found'}), 404
    if not check_availability(teacher.id, data['date'], data['time']):
        return jsonify({'error': '此時段已被預約'}), 400
    duration = data.get('duration', 60)
    total_price = int((duration / 60) * teacher.hourly_rate)
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
    customer = Customer.query.filter_by(phone=data['phone']).first()
    if not customer:
        customer = Customer(name=data['name'], phone=data['phone'])
        db.session.add(customer)
    customer.total_bookings += 1
    customer.total_hours += duration
    customer.total_spent += total_price
    db.session.commit()
    return jsonify({'success': True, 'booking': booking.to_dict()}), 201


# ─────────────────────────────────────────────
# 管理後台 API（維持原有）
# ─────────────────────────────────────────────

@app.route('/admin')
def admin_login():
    return send_from_directory('static', 'admin_login.html')


@app.route('/admin/api/login', methods=['POST'])
def admin_login_api():
    data = request.get_json()
    if data.get('password') == ADMIN_PASSWORD:
        session['admin'] = True
        return jsonify({'success': True})
    return jsonify({'error': 'Invalid password'}), 401


@app.route('/dashboard')
def dashboard():
    return send_from_directory('static', 'admin_dashboard.html')


@app.route('/admin/api/bookings', methods=['GET'])
def admin_get_bookings():
    err = check_admin()
    if err: return err
    date = request.args.get('date')
    status = request.args.get('status')
    query = Booking.query
    if date: query = query.filter_by(date=date)
    if status: query = query.filter_by(status=status)
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
        send_text_message(
            booking.line_user_id,
            f'您的預約已取消\n\n預約編號：{booking.booking_number}\n老師：{booking.teacher.name}\n時間：{booking.date} {booking.time}'
        )
    return jsonify({'success': True})


@app.route('/admin/api/teachers', methods=['GET'])
def admin_get_teachers():
    err = check_admin()
    if err: return err
    return jsonify([t.to_dict() for t in Teacher.query.all()])


@app.route('/admin/api/teachers', methods=['POST'])
def admin_add_teacher():
    err = check_admin()
    if err: return err
    data = request.get_json()
    teacher = Teacher(
        name=data['name'], title=data.get('title', ''),
        specialty=data.get('specialty', ''), bio=data.get('bio', ''),
        hourly_rate=data.get('hourly_rate', 1000), is_active=True
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
        'id': c.id, 'name': c.name, 'phone': c.phone,
        'email': c.email, 'total_bookings': c.total_bookings,
        'total_hours': c.total_hours, 'total_spent': c.total_spent,
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
    convs = AIConversation.query.order_by(AIConversation.created_at.desc()).limit(100).all()
    return jsonify([{
        'id': c.id, 'line_user_id': c.line_user_id,
        'user_message': c.user_message, 'ai_response': c.ai_response,
        'intent': c.intent, 'booking_id': c.booking_id,
        'created_at': c.created_at.strftime('%Y-%m-%d %H:%M') if c.created_at else ''
    } for c in convs])


# ─────────────────────────────────────────────
# 初始化範例資料
# ─────────────────────────────────────────────

def seed():
    if Teacher.query.count() > 0:
        return
    teachers_data = [
        {'name': '陳志豪', 'title': '資深講師',
         'specialty': '數位行銷、社群經營、品牌策略',
         'bio': '10年業界經驗，曾任知名企業行銷總監', 'hourly_rate': 1500},
        {'name': '林美慧', 'title': '專業顧問',
         'specialty': '職涯規劃、履歷優化、面試技巧',
         'bio': '人資背景，協助超過500位求職者成功轉職', 'hourly_rate': 1200},
        {'name': '王俊傑', 'title': '技術專家',
         'specialty': 'Python、資料分析、機器學習',
         'bio': '科技業資深工程師，豐富教學經驗', 'hourly_rate': 1800},
        {'name': '張雅婷', 'title': '語言教師',
         'specialty': '英語教學、多益、商業英文',
         'bio': '英國留學歸國，TESOL認證教師', 'hourly_rate': 1000}
    ]
    for data in teachers_data:
        db.session.add(Teacher(**data))
    db.session.commit()
    print('範例老師資料建立完成')


with app.app_context():
    try:
        db.create_all()
        print('資料庫初始化完成')
        if Teacher.query.count() == 0:
            seed()
    except Exception as e:
        print(f'資料庫初始化錯誤: {e}')

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