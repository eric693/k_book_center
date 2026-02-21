# 老師預約系統

完整的老師課程預約管理系統，整合 LINE AI 自動預約功能。

## 系統特色

- LINE AI 自動預約（無需真人處理）
- 智慧訊息解析（自動辨識老師、日期、時間）
- 雙向通知（自動通知客人與店家）
- 老師管理系統
- 客戶管理系統
- 預約記錄與統計

## 快速啟動

### 1. 安裝套件
```bash
pip install flask flask-sqlalchemy flask-cors requests
```

### 2. 設定 LINE API
1. 到 [LINE Developers Console](https://developers.line.biz/console/)
2. 建立 Messaging API Channel
3. 取得 Channel Access Token 和 Channel Secret
4. 設定環境變數：
```bash
export LINE_CHANNEL_ACCESS_TOKEN="你的_Access_Token"
export LINE_CHANNEL_SECRET="你的_Channel_Secret"
export ADMIN_PASSWORD="你的管理密碼"
```

### 3. 啟動伺服器
```bash
python app.py
```

### 4. 設定 LINE Webhook
在 LINE Developers Console 設定 Webhook URL：
```
https://your-domain.com/webhook/line
```

## 功能說明

### 1. LINE AI 自動預約

#### 支援的訊息格式

**基本預約**
```
預約 陳老師 2/20 15:00
我要訂 王老師 2月20日 下午3點
約 林老師 2/20 3pm
```

**查詢預約**
```
查詢預約
我的預約
```

**查詢老師**
```
老師名單
有哪些老師
```

#### AI 自動處理流程

1. **接收訊息** → LINE 發送訊息到 Webhook
2. **智慧解析** → AI 解析老師、日期、時間
3. **檢查可用性** → 自動查詢老師時段是否可用
4. **建立預約** → 自動生成預約編號
5. **發送通知** → 同時通知客人與店家
6. **記錄對話** → 保存 AI 對話歷史

### 2. 內建老師

| 老師 | 頭銜 | 專長 | 時薪 |
|------|------|------|------|
| 陳志豪 | 資深講師 | 數位行銷、社群經營、品牌策略 | 1500元 |
| 林美慧 | 專業顧問 | 職涯規劃、履歷優化、面試技巧 | 1200元 |
| 王俊傑 | 技術專家 | Python、資料分析、機器學習 | 1800元 |
| 張雅婷 | 語言教師 | 英語教學、多益、商業英文 | 1000元 |

### 3. 訊息解析邏輯

#### 老師名稱解析
- `陳老師` → 陳志豪
- `王老師` → 王俊傑
- 直接名字也可以

#### 日期解析
- `2/20` → 2026-02-20
- `2月20日` → 2026-02-20
- `02/20` → 2026-02-20
- `2026/02/20` → 2026-02-20

#### 時間解析
- `15:00` → 15:00
- `3pm` → 15:00
- `下午3點` → 15:00
- `15點` → 15:00

### 4. 預約流程

#### 網頁預約
```
1. 訪問 http://your-domain.com
2. 選擇老師
3. 選擇日期
4. 選擇時段
5. 填寫姓名、電話
6. 確認預約
7. 收到預約編號
```

#### LINE 預約
```
1. 加入 LINE 官方帳號為好友
2. 傳送預約訊息
3. AI 自動解析並確認
4. 收到預約成功通知
5. 店家同時收到通知
```

## API 端點

### 公開 API

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/` | 學生預約頁面 |
| GET | `/api/teachers` | 取得所有老師 |
| GET | `/api/teachers/:id/availability` | 檢查老師可用時段 |
| POST | `/api/book` | 建立預約 |
| POST | `/webhook/line` | LINE Webhook |

### 管理 API（需密碼）

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/admin/api/login` | 管理員登入 |
| GET | `/admin/api/stats` | 統計資料 |
| GET | `/admin/api/bookings` | 查看所有預約 |
| POST | `/admin/api/bookings/:id/cancel` | 取消預約 |
| GET | `/admin/api/teachers` | 老師管理 |
| POST | `/admin/api/teachers` | 新增老師 |
| GET | `/admin/api/customers` | 客戶管理 |
| GET | `/admin/api/ai-conversations` | AI 對話記錄 |

## 資料庫結構

### Teacher（老師）
- name: 老師姓名
- title: 頭銜
- specialty: 專長
- bio: 簡介
- hourly_rate: 時薪
- is_active: 是否開放預約

### Booking（預約記錄）
- booking_number: 預約編號
- teacher_id: 老師 ID
- customer_name: 客戶姓名
- customer_phone: 電話
- line_user_id: LINE User ID
- date: 日期
- time: 時間
- duration: 課程時長（分鐘）
- total_price: 總價
- status: 狀態（confirmed, cancelled, completed）
- source: 來源（web, line）

### Customer（客戶）
- name: 姓名
- phone: 電話
- line_user_id: LINE User ID
- total_bookings: 總預約次數
- total_hours: 總上課時數
- total_spent: 總消費金額

### AIConversation（AI 對話記錄）
- line_user_id: LINE User ID
- user_message: 用戶訊息
- ai_response: AI 回覆
- intent: 意圖（booking, query）
- booking_id: 關聯的預約 ID

## 通知機制

### 客戶通知（透過 LINE）
- 預約成功確認
- 預約取消通知

### 店家通知
- 新預約通知
- 取消預約通知

## 部署指南

### Render 部署

1. **上傳到 GitHub**
```bash
git add .
git commit -m "老師預約系統"
git push origin main
```

2. **Render 設定**
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT`

3. **環境變數**
```
LINE_CHANNEL_ACCESS_TOKEN=你的Token
LINE_CHANNEL_SECRET=你的Secret
ADMIN_PASSWORD=admin123
```

4. **設定 LINE Webhook**
```
Webhook URL: https://your-app.onrender.com/webhook/line
```

## 測試範例

### 測試 LINE AI 預約

1. **基本預約**
```
傳送：預約 陳老師 2/20 15:00
回覆：預約成功！
      
      預約編號：BK202602200001
      老師：陳志豪
      時間：2026-02-20 15:00
      課程時長：60分鐘
      費用：1500元
      
      請準時出席，期待您的到來！
```

2. **查詢預約**
```
傳送：查詢預約
回覆：您的預約記錄：
      
      BK202602200001
      陳志豪 老師
      2026-02-20 15:00
      費用：1500元
```

3. **老師名單**
```
傳送：老師名單
回覆：目前可預約的老師：
      
      陳志豪 老師
      資深講師
      專長：數位行銷、社群經營、品牌策略
      
      林美慧 老師
      專業顧問
      專長：職涯規劃、履歷優化、面試技巧
      
      ...
```

## 常見問題

### Q: LINE AI 如何辨識預約訊息？
A: 系統使用正則表達式解析訊息，辨識關鍵字（預約、訂、約）和老師名字、日期時間格式。

### Q: 如果老師時段已被預約怎麼辦？
A: AI 會自動通知該時段已被預約，並建議選擇其他時段。

### Q: 需要真人處理嗎？
A: 不需要！AI 完全自動處理預約、通知、記錄。

### Q: 如何取消預約？
A: 客戶可在 LINE 傳送「取消 預約編號」，或管理員在後台取消。

### Q: 支援哪些時間格式？
A: 支援 15:00、3pm、下午3點等多種格式。

### Q: 課程時長固定嗎？
A: 預設為 60 分鐘，可在系統中調整。

## 技術堆疊

- 後端：Python 3.x + Flask
- 資料庫：SQLite + SQLAlchemy
- LINE API：Messaging API
- AI 解析：正則表達式 + 自然語言處理
- 前端：HTML5 + CSS3 + JavaScript
- 設計風格：健身房風格（棕色系）

## 檔案結構

```
專案根目錄/
├── app.py                      # Flask 後端主程式
├── requirements.txt            # Python 套件清單
├── README.md                   # 專案說明
└── static/                     # 前端檔案
    ├── index.html              # 學生預約頁面
    ├── admin_login.html        # 管理員登入
    └── admin_dashboard.html    # 管理後台
```

## 系統網址

部署完成後：

```
學生預約：https://你的網域.onrender.com/
管理登入：https://你的網域.onrender.com/admin
管理後台：https://你的網域.onrender.com/dashboard
```

## 授權

此專案為老師預約管理系統，供內部使用。

## 聯絡資訊

如有問題或建議，歡迎透過系統回饋功能聯繫我們。