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
MAIL_USER = os.environ.get('MAIL_USER', '')
MAIL_PASS = os.environ.get('MAIL_PASS', '')
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY', '')

# 
# 
# 

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

    #  Redis
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


# 
# 
# 


def _build_email_html(title, customer_name, rows, footer_note=''):
    """共用 HTML 模板"""
    rows_html = ''.join(f"""
          <tr style="border-bottom:1px solid #E8E3DB;">
            <td style="padding:12px 8px;color:#6B6B6B;font-size:13px;width:35%;">{k}</td>
            <td style="padding:12px 8px;color:#2C1810;font-weight:600;">{v}</td>
          </tr>""" for k, v in rows)
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;background:#FAF8F5;">
      <div style="background:#2C1810;padding:24px;text-align:center;">
        <h1 style="color:#ffffff;margin:0;font-size:24px;">{title}</h1>
      </div>
      <div style="background:#ffffff;padding:32px;border:1px solid #E8E3DB;">
        <p style="font-size:16px;color:#1A1A1A;">親愛的 {customer_name}，您好！</p>
        <table style="width:100%;border-collapse:collapse;margin:24px 0;">{rows_html}</table>
        <div style="background:#FAF8F5;border:1px solid #E8E3DB;padding:16px;margin-top:8px;">
          <p style="margin:0 0 8px;font-size:13px;font-weight:600;color:#2C1810;">注意事項</p>
          <ul style="margin:0;padding-left:16px;color:#6B6B6B;font-size:13px;line-height:2;">
            <li>請提前 10 分鐘到場準備</li>
            <li>取消或更改請提前 24 小時通知</li>
            <li>遲到超過 15 分鐘視同放棄</li>
          </ul>
          {f'<p style="margin-top:8px;color:#E05A2B;font-size:13px;">{footer_note}</p>' if footer_note else ''}
        </div>
      </div>
      <div style="text-align:center;padding:16px;color:#6B6B6B;font-size:12px;">
        K書中心 &copy; 2026 · 此為系統自動發送，請勿回覆
      </div>
    </div>"""


def _send_via_sendgrid(to_email, subject, html):
    """透過 SendGrid API 發送 Email（Render 免費方案可用）"""
    if not SENDGRID_API_KEY:
        return False, 'SENDGRID_API_KEY 未設定'
    if not MAIL_USER:
        return False, 'MAIL_USER（寄件人）未設定'
    payload = {
        'personalizations': [{'to': [{'email': to_email}]}],
        'from': {'email': MAIL_USER},
        'subject': subject,
        'content': [{'type': 'text/html', 'value': html}]
    }
    try:
        r = requests.post(
            'https://api.sendgrid.com/v3/mail/send',
            headers={
                'Authorization': f'Bearer {SENDGRID_API_KEY}',
                'Content-Type': 'application/json'
            },
            json=payload,
            timeout=15
        )
        if r.status_code in (200, 202):
            return True, 'OK'
        else:
            return False, f'SendGrid HTTP {r.status_code}: {r.text}'
    except Exception as e:
        return False, str(e)


def send_booking_email(to_email, customer_name, booking):
    """發送預約確認 Email（SendGrid）"""
    if not to_email:
        return False
    teacher_name = booking.teacher.name if booking.teacher else ''
    subject = f'【K書中心】預約確認 - {booking.booking_number}'
    rows = [
        ('預約編號', booking.booking_number),
        ('老師', f'{teacher_name} 老師'),
        ('日期', booking.date),
        ('時間', booking.time),
        ('課程時長', f'{booking.duration} 分鐘'),
        ('費用', f'NT$ {booking.total_price:,}'),
    ]
    html = _build_email_html('K書中心預約確認', customer_name, rows)
    ok, msg = _send_via_sendgrid(to_email, subject, html)
    if ok:
        print(f'Email 發送成功: {to_email}')
    else:
        print(f'Email 發送失敗: {msg}')
    return ok


def send_cancel_email(to_email, customer_name, booking):
    """發送取消通知 Email（SendGrid）"""
    if not to_email:
        return False
    teacher_name = booking.teacher.name if booking.teacher else ''
    subject = f'【K書中心】預約取消通知 - {booking.booking_number}'
    rows = [
        ('預約編號', booking.booking_number),
        ('老師', f'{teacher_name} 老師'),
        ('日期', booking.date),
        ('時間', booking.time),
    ]
    html = _build_email_html('K書中心預約取消通知', customer_name, rows,
                             footer_note='如需重新預約請透過 LINE 或網頁操作。')
    ok, msg = _send_via_sendgrid(to_email, subject, html)
    if ok:
        print(f'取消 Email 發送成功: {to_email}')
    else:
        print(f'取消 Email 發送失敗: {msg}')
    return ok



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
        print(f'Push Flex : {e}')
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
            print(f'Reply Flex : {r.status_code} {r.text}')
        return r.status_code == 200
    except Exception as e:
        print(f'Reply Flex : {e}')
        return False


def reply_text_message(reply_token, text):
    """Reply """
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
        print(f'Reply Text : {e}')
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
        print(f'Push Text : {e}')
        return False


def send_admin_notification(message):
    print(f': {message}')
    return True


# 
# Flex Message 
# 

def build_welcome_flex():
    """"""
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "K書中心", "weight": "bold",
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
                        "label": "查看老師名單",
                        "text": "老師名單"
                    },
                    "height": "sm"
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "message",
                        "label": "查詢我的預約",
                        "text": "查詢預約"
                    },
                    "height": "sm"
                }
            ]
        }
    }


def build_teacher_carousel(teachers):
    """ Carousel"""
    bubbles = []
    for t in teachers:
        # 
        _spec = (t.specialty or '').strip()
        specialty_short = (_spec if _spec else '專業講師')[:30] + ('...' if len(_spec) > 30 else '')

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
                        "text": t.title or "講師",
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
    """7"""
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
                "label": f"{d.strftime('%m/%d')} ({weekday})",
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
    """"""
    if not available_times:
        return {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "此日期已無可用時段",
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
                        "label": "<- 返回",
                        "data": f"action=select_teacher&teacher_id={teacher_id}&teacher_name={teacher_name}",
                        "displayText": "重新選擇日期"
                    }
                }]
            }
        }

    # 3
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
            # 
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
                {"type": "text", "text": f"{d_fmt}  請選擇時段",
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
    """"""
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
                _info_row("老師", f"{teacher_name} 老師"),
                _info_row("日期", f"{d_fmt} (週{weekday})"),
                _info_row("時間", time),
                _info_row("時長", "60 分鐘"),
                _info_row("費用", f"$ {price} 元"),
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
                        "label": "<- 返回",
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
                        "label": "確認預約",
                        "data": f"action=confirm_booking&teacher_id={teacher_id}&date={date}&time={time}",
                        "displayText": f"確認預約 {teacher_name} 老師 {date} {time}"
                    }
                }
            ]
        }
    }


def build_booking_success_flex(booking):
    """"""
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
                {"type": "text", "text": "預約成功！",
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
                _info_row("老師", f"{teacher_name} 老師"),
                _info_row("日期", f"{d_fmt} (週{weekday})"),
                _info_row("時間", booking.time),
                _info_row("時長", f"{booking.duration} 分鐘"),
                _info_row("費用", f"NT$ {booking.total_price} 元"),
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
    """"""
    if not bookings:
        return {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "此日期已無可用時段",
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
        teacher_name = b.teacher.name if b.teacher else ''
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
                    {"type": "text", "text": f"日期：{d_fmt}  時間：{b.time}",
                     "size": "sm", "color": "#555555"},
                    {"type": "text", "text": f"費用：${b.total_price} 元",
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
    """註冊卡片 - 提供快速輸入按鈕"""
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "首次預約，請先完成註冊",
                 "weight": "bold", "size": "lg", "color": "#ffffff"},
                {"type": "text", "text": "只需要姓名和手機號碼",
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
                    "text": "點選下方按鈕，修改成您的真實姓名和手機號碼後送出即可完成註冊。",
                    "wrap": True,
                    "size": "sm",
                    "color": "#555555"
                },
                {
                    "type": "text",
                    "text": "格式：  註冊 姓名 手機號碼",
                    "wrap": True,
                    "size": "sm",
                    "color": "#8E44AD",
                    "weight": "bold",
                    "margin": "sm"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#8E44AD",
                    "height": "sm",
                    "action": {
                        "type": "uri",
                        "label": "點此輸入註冊資料",
                        "uri": f"https://line.me/R/oaMessage/@?%E8%A8%BB%E5%86%8A%20%E6%82%A8%E7%9A%84%E5%A7%93%E5%90%8D%200912345678"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "clipboard",
                        "label": "複製格式範例",
                        "clipboardText": "註冊 張小明 0912345678"
                    }
                }
            ]
        }
    }


def _info_row(label, value):
    """"""
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


# 
# LINE Webhook
# 

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
            print('LINE ')
            return 'Invalid signature', 403

    try:
        payload = json.loads(body) if body else {}
        events = payload.get('events', [])
    except Exception as e:
        print(f'JSON : {e}')
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

            #   
            if event_type == 'message' and event.get('message', {}).get('type') == 'text':
                text = event['message']['text'].strip()
                handle_text_event(reply_token, user_id, text)

            #  Postback
            elif event_type == 'postback':
                data = event.get('postback', {}).get('data', '')
                handle_postback_event(reply_token, user_id, data)

            #   
            elif event_type == 'follow':
                flex = build_welcome_flex()
                reply_flex_message(reply_token, 'K書中心服務選單', flex)

        except Exception as e:
            print(f' event : {e}')
            import traceback; traceback.print_exc()

    return 'OK', 200


def handle_text_event(reply_token, user_id, text):
    """"""

    # 
    if '' in text or '' in text:
        teachers = Teacher.query.filter_by(is_active=True).all()
        flex = build_teacher_carousel(teachers)
        reply_flex_message(reply_token, f'老師名單，共 {len(teachers)} 位', flex)
        return

    # 
    if '' in text or '' in text:
        bookings = Booking.query.filter_by(
            line_user_id=user_id, status='confirmed'
        ).order_by(Booking.date, Booking.time).all()
        flex = build_my_bookings_flex(bookings)
        reply_flex_message(reply_token, f'我的預約，共 {len(bookings)} 筆', flex)
        return

    #   
    if text.startswith(''):
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
            reply_text_message(reply_token, f'  {name}')
        else:
            reply_text_message(reply_token, '\n  \n  0912345678')
        return

    # 
    flex = build_welcome_flex()
    reply_flex_message(reply_token, 'K書中心服務選單', flex)


def handle_postback_event(reply_token, user_id, data):
    """ Postback"""
    params = dict(p.split('=', 1) for p in data.split('&') if '=' in p)
    action = params.get('action', '')

    # 1. 選擇老師 -> 顯示日期選擇
    if action == 'select_teacher':
        teacher_id = int(params.get('teacher_id', 0))
        teacher = Teacher.query.get(teacher_id)
        if not teacher:
            reply_text_message(reply_token, '')
            return
        flex = build_date_picker_flex(teacher.id, teacher.name)
        reply_flex_message(reply_token, f'預約 {teacher.name} 老師 - 選擇日期', flex)

    # 2. 選擇日期 -> 顯示時段
    elif action == 'select_date':
        teacher_id = int(params.get('teacher_id', 0))
        date = params.get('date', '')
        teacher = Teacher.query.get(teacher_id)
        if not teacher or not date:
            reply_text_message(reply_token, '')
            return
        available = get_available_times(teacher_id, date)
        flex = build_time_picker_flex(teacher_id, teacher.name, date, available)
        reply_flex_message(reply_token, f'{date} 可預約時段', flex)

    # 3. 選擇時段 -> 顯示確認畫面
    elif action == 'select_time':
        teacher_id = int(params.get('teacher_id', 0))
        date = params.get('date', '')
        time = params.get('time', '')
        teacher = Teacher.query.get(teacher_id)
        if not teacher:
            reply_text_message(reply_token, '')
            return
        price = teacher.hourly_rate
        flex = build_confirm_flex(teacher.name, date, time, price, teacher_id)
        reply_flex_message(reply_token, '確認預約資訊', flex)

    # 4. 確認預約 -> 完成
    elif action == 'confirm_booking':
        teacher_id = int(params.get('teacher_id', 0))
        date = params.get('date', '')
        time = params.get('time', '')
        teacher = Teacher.query.get(teacher_id)

        if not teacher:
            reply_text_message(reply_token, '')
            return

        if not check_availability(teacher_id, date, time):
            reply_text_message(reply_token, f' {date} {time} ')
            return

        customer = Customer.query.filter_by(line_user_id=user_id).first()
        if not customer:
            # 
            flex = build_register_flex(teacher_id, date, time)
            reply_flex_message(reply_token, '首次預約請先完成註冊', flex)
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
            f'{booking.booking_number} | {customer.name} | {teacher.name} | {date} {time}'
        )

        flex = build_booking_success_flex(booking)
        reply_flex_message(reply_token, f'預約成功 {booking.booking_number}', flex)

    # 5. 
    elif action == 'cancel_booking':
        booking_id = int(params.get('booking_id', 0))
        booking = Booking.query.get(booking_id)
        if not booking or booking.line_user_id != user_id:
            reply_text_message(reply_token, '')
            return
        booking.status = 'cancelled'
        db.session.commit()
        reply_text_message(
            reply_token,
            f'  {booking.booking_number}\n{booking.teacher.name}  {booking.date} {booking.time}'
        )

    else:
        reply_text_message(reply_token, '')


# 
#  APIWeb 
# 

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
        return jsonify({'error': '此時段已被預約，請選擇其他時間'}), 400
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
    email = data.get('email', '').strip()
    customer = Customer.query.filter_by(phone=data['phone']).first()
    if not customer:
        customer = Customer(name=data['name'], phone=data['phone'], email=email)
        db.session.add(customer)
        db.session.flush()  # 確保 customer 有 id，避免 NoneType 錯誤
    else:
        if email and not customer.email:
            customer.email = email
    customer.total_bookings += 1
    customer.total_hours += duration
    customer.total_spent += total_price
    db.session.commit()

    # 重新查詢 booking 以載入 teacher 關聯
    booking = Booking.query.get(booking.id)
    send_booking_email(email, data['name'], booking)

    return jsonify({'success': True, 'booking': booking.to_dict()}), 201


# 
#  API
# 

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
    # 寄取消通知給 LINE 用戶
    if booking.line_user_id:
        teacher_name = booking.teacher.name if booking.teacher else ''
        send_text_message(
            booking.line_user_id,
            f'您的預約已取消\n\n預約編號：{booking.booking_number}\n老師：{teacher_name} 老師\n時間：{booking.date} {booking.time}\n\n如需重新預約請傳送「老師名單」'
        )
    # 寄取消通知 Email
    customer = Customer.query.filter_by(phone=booking.customer_phone).first()
    if customer and customer.email:
        send_cancel_email(customer.email, booking.customer_name, booking)
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


# 
# 
# 

def seed():
    if Teacher.query.count() > 0:
        return
    teachers_data = [
        {'name': '陳志豪', 'title': '資深講師',
         'specialty': '數位行銷、社群經營、品牌策略',
         'bio': '擁有10年以上數位行銷實務經驗，協助超過百家企業建立品牌策略。', 'hourly_rate': 1500},
        {'name': '林美慧', 'title': '專業顧問',
         'specialty': '職涯規劃、履歷優化、面試技巧',
         'bio': '曾任500強企業HR主管，專精職涯轉型與求職輔導。', 'hourly_rate': 1200},
        {'name': '王俊傑', 'title': '技術專家',
         'specialty': 'Python、資料分析、機器學習',
         'bio': '資深資料科學家，擅長Python教學與AI應用實務開發。', 'hourly_rate': 1800},
        {'name': '張雅婷', 'title': '語言教師',
         'specialty': '英語教學、多益、商業英文',
         'bio': '持TESOL國際英語教學認證，多益教學經驗豐富。', 'hourly_rate': 1000}
    ]
    for data in teachers_data:
        db.session.add(Teacher(**data))
    db.session.commit()
    print('')


with app.app_context():
    try:
        db.create_all()
        print('')
        if Teacher.query.count() == 0:
            seed()
    except Exception as e:
        print(f': {e}')

if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    with app.app_context():
        db.create_all()
        seed()
    print('\n  ')
    print('  http://localhost:5000')
    print('  http://localhost:5000/admin')
    print(f'      {ADMIN_PASSWORD}')
    print(f'  LINE Webhook: http://your-domain.com/webhook/line\n')
    app.run(debug=True, port=5000)