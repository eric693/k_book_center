# K書中心預約系統

完整的 K書中心管理系統，整合 LINE AI 自動預約功能。

## 系統特色

- LINE AI 自動預約（無需真人處理）
- 智慧訊息解析（自動辨識日期、時間、座位類型）
- 雙向通知（自動通知客人與店家）
- 座位管理系統
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
python app_studyroom.py
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
預約 2/20 15:00-17:00 單人座位
我要訂 2月20日 下午3點到5點 包廂
想約 2/20 3pm-5pm A1座位
```

**查詢預約**
```
查詢預約
我的預約
```

**取消預約**
```
取消 BK202602200001
```

**查詢資訊**
```
營業時間
價格
```

#### AI 自動處理流程

1. **接收訊息** → LINE 發送訊息到 Webhook
2. **智慧解析** → AI 解析日期、時間、座位類型
3. **檢查可用性** → 自動查詢座位是否可用
4. **建立預約** → 自動生成預約編號
5. **發送通知** → 同時通知客人與店家
6. **記錄對話** → 保存 AI 對話歷史

### 2. 座位類型

| 類型 | 容納人數 | 時薪 | 說明 |
|------|---------|------|------|
| 單人座位 | 1人 | 50元 | 獨立座位，插座，WiFi |
| 雙人座位 | 2人 | 80元 | 適合討論，2個插座 |
| 小包廂 | 4人 | 150元 | 獨立空間，白板，投影 |
| VIP包廂 | 6人 | 250元 | 會議桌，投影，獨立空調 |

### 3. 訊息解析邏輯

#### 日期解析
- `2/20` → 2026-02-20
- `2月20日` → 2026-02-20
- `02/20` → 2026-02-20
- `2026/02/20` → 2026-02-20

#### 時間解析
- `15:00-17:00` → 15:00 到 17:00
- `3pm-5pm` → 15:00 到 17:00
- `下午3點到5點` → 15:00 到 17:00
- `15點到17點` → 15:00 到 17:00

#### 座位類型解析
- `單人` / `一人` → single
- `雙人` / `兩人` / `2人` → double
- `小包廂` / `小間` → group
- `大包廂` / `VIP` / `大間` → vip

### 4. 預約流程

#### 網頁預約
```
1. 訪問 http://your-domain.com
2. 選擇日期、時間、座位
3. 填寫姓名、電話
4. 確認預約
5. 收到預約編號
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
| GET | `/api/rooms` | 取得所有座位 |
| GET | `/api/rooms/:id/availability` | 檢查座位可用性 |
| POST | `/api/book` | 建立預約 |
| POST | `/webhook/line` | LINE Webhook |

### 管理 API（需密碼）

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/admin/api/bookings` | 查看所有預約 |
| POST | `/admin/api/bookings/:id/cancel` | 取消預約 |
| GET | `/admin/api/rooms` | 座位管理 |
| POST | `/admin/api/rooms` | 新增座位 |
| GET | `/admin/api/customers` | 客戶管理 |
| GET | `/admin/api/stats` | 統計資料 |

## 資料庫結構

### Room（座位）
- name: 座位名稱（A1, B1, 包廂1）
- type: 類型（single, double, group, vip）
- capacity: 容納人數
- hourly_rate: 時薪
- description: 說明
- is_active: 是否開放

### Booking（預約記錄）
- booking_number: 預約編號
- room_id: 座位 ID
- customer_name: 客戶姓名
- customer_phone: 電話
- line_user_id: LINE User ID
- date: 日期
- start_time: 開始時間
- end_time: 結束時間
- hours: 時數
- total_price: 總價
- status: 狀態（confirmed, cancelled, completed）
- source: 來源（web, line）

### Customer（客戶）
- name: 姓名
- phone: 電話
- line_user_id: LINE User ID
- total_bookings: 總預約次數
- total_hours: 總使用時數
- total_spent: 總消費金額
- is_vip: 是否為 VIP

### AIConversation（AI 對話記錄）
- line_user_id: LINE User ID
- user_message: 用戶訊息
- ai_response: AI 回覆
- intent: 意圖（booking, query, cancel）
- booking_id: 關聯的預約 ID

## 通知機制

### 客戶通知（透過 LINE）
- 預約成功確認
- 預約取消通知
- 預約提醒（可擴充）

### 店家通知
- 新預約通知
- 取消預約通知
- 每日預約摘要（可擴充）

## 進階功能（可擴充）

### 已實作
- [x] LINE AI 自動預約
- [x] 智慧訊息解析
- [x] 雙向通知
- [x] 座位管理
- [x] 客戶管理
- [x] 預約統計

### 可擴充
- [ ] 預約提醒（提前1小時通知）
- [ ] 會員制度（VIP 折扣）
- [ ] 線上支付整合
- [ ] 簽到系統
- [ ] 延長時間功能
- [ ] 座位使用率分析
- [ ] 客戶偏好分析
- [ ] 優惠券系統

## 部署指南

### Render 部署

1. **上傳到 GitHub**
```bash
git add .
git commit -m "K書中心預約系統"
git push origin main
```

2. **Render 設定**
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app_studyroom:app --bind 0.0.0.0:$PORT`

3. **環境變數**
```
LINE_CHANNEL_ACCESS_TOKEN=你的Token
LINE_CHANNEL_SECRET=你的Secret
ADMIN_PASSWORD=管理密碼
SECRET_KEY=自動生成
```

4. **設定 LINE Webhook**
```
Webhook URL: https://your-app.onrender.com/webhook/line
```

### Railway 部署

類似 Render，設定相同的環境變數即可。

## 測試範例

### 測試 LINE AI 預約

1. **基本預約**
```
傳送：預約 2/20 15:00-17:00 單人座位
回覆：預約成功！
      預約編號：BK202602200001
      座位：A1
      時間：2026-02-20 15:00-17:00
      時數：2小時
      費用：100元
```

2. **查詢預約**
```
傳送：查詢預約
回覆：您的預約記錄：
      BK202602200001
      A1
      2026-02-20 15:00-17:00
      費用：100元
```

3. **營業時間**
```
傳送：營業時間
回覆：我們的營業時間是每天 08:00 - 23:00
```

## 常見問題

### Q: LINE AI 如何辨識預約訊息？
A: 系統使用正則表達式解析訊息，辨識關鍵字（預約、訂、約）和日期時間格式。

### Q: 如果座位已被預約怎麼辦？
A: AI 會自動尋找同類型的其他座位並建議替代方案。

### Q: 需要真人處理嗎？
A: 不需要！AI 完全自動處理預約、通知、記錄。

### Q: 如何取消預約？
A: 客戶可在 LINE 傳送「取消 預約編號」，或管理員在後台取消。

### Q: 支援哪些時間格式？
A: 支援 15:00-17:00、3pm-5pm、下午3點到5點等多種格式。

## 技術堆疊

- 後端：Python 3.x + Flask
- 資料庫：SQLite + SQLAlchemy
- LINE API：Messaging API
- AI 解析：正則表達式 + 自然語言處理
- 前端：HTML5 + CSS3 + JavaScript

## 授權

此專案為 K書中心管理系統，供內部使用。

## 聯絡資訊

如有問題或建議，歡迎透過系統回饋功能聯繫我們。