# Social Engagement Automation Lab

[English](./README.md) · **繁體中文**

> **本地社群帳號自動化與大量互動研究平台**
>
> 專為研究 Instagram 類型社群架構之 Session 管理、Playwright 瀏覽器自動化、HTTP 請求鏈路、批次按讚、資料庫併發寫入與限流機制所建立的本地沙盒系統

<p align="center">
  <a href="https://github.com/ReiKama414/social-engagement-lab">GitHub</a> ·
  <a href="https://reikama414.vercel.app/">個人網站</a> ·
  <a href="#快速開始">快速開始</a> ·
  <a href="#授權">授權</a>
</p>

---

## 安全邊界與研究宣告

本專案為純本地實驗室環境，嚴格遵守研究邊界：

- **不連接真實 Instagram 伺服器**，所有請求限定於 `localhost`（`127.0.0.1`）
- **不使用任何非官方 Private API**，所有協定均在本地 FastAPI 模擬伺服器上實現
- **不蒐集或使用真實 Instagram Session Cookie**
- **不繞過真實平台 CAPTCHA、設備指紋或進行 IP 代理輪換**
- 所有虛擬帳號（100～10,000）與貼文資料均儲存於本機 SQLite 資料庫中

---

## 系統架構與技術棧

| 層級 | 技術選型 | 核心功能 |
| :--- | :--- | :--- |
| **前端應用** | Next.js 16 + TypeScript + Tailwind CSS v4 | 專業開發者控制台、Instagram 風格 Feed、網路請求檢查器、互動式流程圖 |
| **後端伺服器** | FastAPI + Python 3.11 + Uvicorn | RESTful API、Inspector 中間件、自適應 Rate Limiter、WebSocket 即時廣播 |
| **瀏覽器自動化** | Playwright（Chromium Headless / Headed） | 隔離 Context 登入、貼文尋找、按讚點擊、HTTP 回應攔截、SQLite 直讀驗證 |
| **儲存引擎** | SQLite 3（WAL 模式 + Busy Timeout） | 支援高併發讀寫、Atomic Transaction、自動資料庫鎖保護 |
| **即時通訊** | WebSocket（`/ws`） | 任務進度、即時 Log、按讚計數同步、壓測指標即時推送 |

---

## 快速開始

專案已內建完整的環境虛擬目錄與啟動腳本

### 方式一：一鍵雙擊啟動（推薦）

雙擊根目錄下的 `start.bat`，系統將自動於獨立終端視窗啟動：

1. **後端服務（FastAPI）** — [http://127.0.0.1:8000](http://127.0.0.1:8000)
2. **前端服務（Next.js）** — [http://localhost:3000](http://localhost:3000)
3. **獨立測試頁面（Mock UI）** — [http://127.0.0.1:8000/mock-social](http://127.0.0.1:8000/mock-social)

### 方式二：PowerShell 啟動

```powershell
.\start.ps1
```

### 方式三：分開手動啟動

```powershell
# 1. 啟動後端
.\run_backend.bat

# 2. 啟動前端
.\run_frontend.bat
```

---

## 自動化測試驗證

本專案附帶完整自動化測試，涵蓋 API 邏輯、Session 驗證、Rate Limiting、資料庫寫入與 Playwright 瀏覽器完整流程

雙擊執行 `run_tests.bat` 或在終端機執行：

```powershell
# 執行 API 與整合測試
.\backend\venv\Scripts\pytest -v backend\tests\test_api.py

# 執行 Playwright 真實瀏覽器端到端測試
.\backend\venv\Scripts\pytest -v backend\tests\test_playwright.py
```

---

## 五大研究模組

### 1. 模擬社群平台（Mock Social Feed）— `/feed`

- 具備完整 Instagram 風格動態貼文牆
- 支援帳號註冊、密碼驗證、獨立 Session Token（Bearer / Cookie）
- 支援按讚與取消讚，點擊後觸發真實 SQLite 資料庫寫入與樂觀鎖
- 支援 **「Simulate Expired Session」** 按鈕，人為模擬憑證過期並觀察 HTTP 401 攔截
- 提供「查看所有互動帳號（Likers Drawer）」，可檢視每筆按讚是由 BROWSER 還是 API 模式產生

### 2. 批次帳號管理（Batch Account Fleet）— `/accounts`

- **一鍵產生虛擬帳號**：支援 `+100`、`+1,000`、`+5,000` 與 `+10,000` 個帳號
- 採用 SQLite `executemany` 批次寫入最佳化，建立 10,000 個獨立帳號僅需約 0.8 秒
- 每個帳號皆具備獨立 ID、頭像、群組標籤（Group Tag）、狀態（ACTIVE / DISABLED / RATE_LIMITED）與預先簽發的有效 Session
- 支援搜尋、群組篩選、批次啟用、批次停用、批次刪除與 Session 過期操作

### 3. Playwright 任務控制中心（Task Control Center）— `/tasks`

- 專業管理儀表板，支援兩大執行模式：
  - **Playwright Fleet**：使用真正的 Chromium 瀏覽器隔離環境，執行 8 步驟完整自動化流程：`啟動瀏覽器 → 開啟頁面 → 填入帳密登入 → 尋找貼文 → 點擊按讚 → 攔截 API 回應 → 直查 SQLite 驗證 → 關閉 Context`
  - **High-Speed API**：使用直接持有 Session 的異步工作池，適合快速驗證千個帳號互動
- 支援 **Worker Pool 併發數控制**（限制 2～8 個瀏覽器 Context，避免耗盡記憶體）
- 支援 **操作間隔（Delay / Jitter）** 設定（0～2000ms）
- 支援 **開始、暫停、恢復、取消** 任務控制
- 每次任務皆具備唯一 Task ID，並提供毫秒級 Live 執行終端日誌

### 4. 網路請求研究介面（Network Inspector）— `/inspector`

- **全方位 HTTP 審計**：HTTP Method、Path、Timestamp、Latency (ms)
- 敏感憑證遮罩（Bearer Token 自動去敏如 `Bearer sess_****abcd`）
- Request Body 與 Response Body JSON 預覽
- Session 驗證分析（查詢 sessions 表、有效期限計算、帳號啟用狀態）
- SQLite WAL 變更分析（受影響行數、Likes 數前置與後置值變化）
- **cURL 複製功能**：一鍵將任何擷取到的請求複製為終端機可直接執行的標準 cURL 命令
- **完整追蹤 JSON 匯出**：下載完整生命週期追蹤數據進行離線分析
- **Timing Waterfall 瀑布耗時分析**：視覺化拆解網路傳輸、路由匹配、憑證驗證、SQLite 交易與序列化耗時
- **互動式 7 層執行生命週期圖**：

  ```
  Browser → HTTP Request → FastAPI → Session Validation → SQLite → Response → UI Update
  ```

  可點擊任意層級逐步觀察該層的內部狀態、耗時與資料轉化

### 5. 高併發效能與壓力測試（Stress Benchmark）— `/benchmark`

- 專門針對本地 API 與資料庫鎖進行高吞吐壓測（支援至 10,000 個虛擬帳號）
- **即時指標串流與視覺化**：
  - **即時 RPS 走勢曲線（Live SVG RPS Curve）**
  - **成功率 %** 與成功/失敗數
  - **延遲百分位分佈（P50、P90、P95、P99）**
  - **資料庫寫入速度（DB Writes/sec）**
  - **爭端與錯誤分析**：RateLimit_429、Duplicate_Like_400、SessionExpired_401、DB_Locked_Timeout 等

---

## 雙語系統（應用內）

專案嚴格遵循「**主要中文，副英文，前後台一致**」設計規範：

- 導航列頂部提供 `[繁中 | EN]` 一鍵即時切換按鈕
- 本地獨立動態牆 `/mock-social` 與所有前台/後台儀表板同步支援繁體中文與英文
- 網路檢查器的生命週期階層名稱、日誌標籤均具備中英雙語對照

---

## 授權

MIT © [ReiKama414](https://github.com/ReiKama414)

可自由使用、複製、修改、散佈（含商業用途），需保留版權與授權聲明，軟體不提供任何擔保

見 [LICENSE](./LICENSE)

---

<sub>作者 [ReiKama414](https://github.com/ReiKama414) · [個人網站](https://reikama414.vercel.app/)</sub>
