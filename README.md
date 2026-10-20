# 喜餅訂單匯流

門市照舊用 Excel 記喜餅訂單，把檔案傳進有中央廚房 LINE OA 的群組；後端保存原檔、合併成總表，並回覆傳檔的人。

## 本機啟動

需要 Docker。一個指令把 app 和 Postgres 一起啟動：

```sh
docker compose up --build
```

開 <http://localhost:8000>，先用下面的 demo 帳號登入（門市沒有帳號，也不需要登入）：

- 總表：`/orders`，可以依門市和取貨日篩選。
- 上傳紀錄：`/uploads`，每一份原檔都可以下載，也記錄是從 LINE 還是由哪個帳號在模擬頁送出的。
- 模擬群組上傳：`/demo/upload`（demo 用，門市不會看到）。選一位傳檔者、上傳 `mock_data/` 裡的檔案，畫面上的回覆就是 LINE 群組會收到的內容。

## Demo 帳號

`bakery-init`（本機由 compose 的 `init` 服務執行，部署時由 Cloud Run job 執行）會建好這幾個帳號，密碼都是 `demo1234`：

| 帳號 | 誰 | 看得到 |
|---|---|---|
| `hq-lin` | 總部人員 林雅文 | 全部營運頁面：總表、上傳紀錄、模擬群組上傳 |
| `hq-chen` | 總部人員 陳志明 | 同上（總部每人一個帳號，紀錄裡才分得出是誰做的） |
| `kitchen` | 中央廚房（共用） | 只有總表和廚房彙總 |
| `owner` | 老闆 | 全部頁面 |

密碼只存 argon2 雜湊。登入狀態是簽章過的 cookie，金鑰來自環境變數 `SESSION_SECRET`；本機沒設定時用開發用的預設值。部署時設 `BAKERY_ENV=production`，這時沒有設定 `SESSION_SECRET`（或少於 32 字元、或用的是預設值）app 會拒絕啟動，cookie 也只走 HTTPS。

## 開發

```sh
uv sync
uv run pytest   # 需要 Docker（testcontainers 會起一個 Postgres）
```

## 部署（Cloud Run＋Neon）

app 跑在 Google Cloud Run 的 `asia-east1`（台灣），最少執行個體數 0；資料庫是 Neon 的 Postgres，連線走 TLS。原檔以 `bytea` 存在 Postgres，容器重啟不會遺失。secrets 只放在 Secret Manager，不進 repo。

### 事前準備（只做一次）

1. **Google Cloud**：建一個 project 並綁定帳單帳戶（Cloud Run 即使在免費額度內也要求綁帳單）。安裝 [gcloud CLI](https://cloud.google.com/sdk/docs/install)，執行 `gcloud auth login`。帳號要是該 project 的 Owner（腳本會啟用 API、建 service account、設定 IAM）。
2. **Neon**：註冊免費方案（不需信用卡），建一個 project：
   - Region 選 **AWS Asia Pacific (Singapore)**（`aws-ap-southeast-1`，離台灣最近，建立後不能改）。
   - Compute size 固定 **0.25 CU**（見下方成本估算）。
   - 在 Connection details 關掉 *Connection pooling*，複製**直連**的連線字串（主機名稱沒有 `-pooler`）。Neon 給的字串已經帶 `sslmode=require`，原樣使用即可。
3. 本機需要 `bash`、`git`、`openssl`。不需要 Docker：映像檔由 Cloud Build 建置。

### 部署

```sh
GCP_PROJECT=<project-id> \
DATABASE_URL='postgresql://<user>:<password>@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require' \
scripts/deploy.sh
```

腳本可重跑，重跑就是重新部署；之後部署不必再給 `DATABASE_URL`（沿用 Secret Manager 裡的值）。它依序：

1. 啟用 Cloud Run、Artifact Registry、Cloud Build、Secret Manager API；建立映像檔倉庫（只保留最近 3 個映像檔）與 app 專用的 service account。
2. 把 `DATABASE_URL` 存成 Secret Manager 的 `bakery-database-url`；`SESSION_SECRET`（登入 cookie 的簽章金鑰）沒給就自動產生一組存成 `bakery-session-secret`。值有變才新增版本。沒有 `sslmode=require`（或 `verify-ca`／`verify-full`）的 `DATABASE_URL` 直接拒絕。
3. 用 Cloud Build 建置 `Dockerfile`（非 root 使用者執行，監聽 Cloud Run 給的 `PORT`）。
4. 以 Cloud Run job `bakery-orders-init` 執行 `bakery-init`（Alembic 升到 head＋種入參考資料與 demo 帳號），等它成功才往下。
5. 部署 service `bakery-orders`：`--min-instances 0 --max-instances 2`、公開存取、secrets 以參照方式掛成環境變數、`BAKERY_ENV=production`、`PUBLIC_BASE_URL`（回覆裡的連結用；預設是 Cloud Run 網址，用自訂網域時自行設定）。
6. 印出公開網址。

`DRY_RUN=1 GCP_PROJECT=x scripts/deploy.sh` 只印出會執行的 gcloud 指令（不印 secret 值）。

部署後的驗收：以 `hq-lin` 登入，開 `<網址>/demo/upload`，傳檔者選「草屯和平店 門市帳號」，上傳 `mock_data/day1/NT01_草屯和平店.xlsx`，回覆應為「草屯和平店（NT01）：收到 5 張喜餅訂單、9 筆訂單明細。」，`/orders` 看得到這 5 張訂單，`/uploads` 下載的原檔與上傳的一模一樣。

### Migration 為什麼用 Cloud Run job

`bakery-init` 不在容器啟動時跑，而是每次部署跑一次 Cloud Run job：

- 最少執行個體數 0，每次冷啟動都跑 migration 會拖慢第一個請求（還要等 Neon 從暫停中喚醒）；而 LINE 的 reply token 只有 1 分鐘有效。
- 同時冷啟動多個執行個體時，各自跑 Alembic 會互相競爭。
- migration 失敗時腳本停在第 4 步，新版本不會上線，舊版本照常服務。

本機 `compose.yaml` 用同樣的分法：`init` 服務跑完 `bakery-init`，`app` 才啟動。

### 每月成本估算

目標是全部落在免費額度內：**每月 0 元**。假設 6 家門市、每店每天上傳 2 次（約 400 次／月），總部與廚房每天開網頁約 100 次（約 3,000 次／月）。

| 服務 | 免費額度 | 估計用量 | 費用 |
| --- | --- | --- | --- |
| Cloud Run（request-based） | 每月 180,000 vCPU-秒、360,000 GiB-秒、200 萬次請求 [1] | 約 4,000 次請求；保守抓每次佔 1 vCPU 2 秒（含冷啟動）＝8,000 vCPU-秒、4,000 GiB-秒（512 MiB） | 0 |
| Cloud Run job（instance-based） | 每月 240,000 vCPU-秒、450,000 GiB-秒 [1] | 每次部署約 30 vCPU-秒 | 0 |
| Neon Free | 每 project 100 CU-小時／月、1 GB 儲存、5 GB egress；閒置 5 分鐘自動暫停 [2] | 0.25 CU 時，100 CU-小時＝每月 400 小時運算；就算營業時間每天 12 小時都醒著也只用 90 CU-小時。原檔每份約 7 KB，一年約 35 MB | 0 |
| Secret Manager | 6 個有效版本、每月 10,000 次存取 [3] | 2 個 secret；每次執行個體啟動讀取 2 次 | 0 |
| Artifact Registry | 0.5 GB 儲存 [4] | 只保留最近 3 個映像檔 | 0 |
| Cloud Build | 每月 2,500 build-分鐘（e2-standard-2 預設 pool）[5] | 每次部署約 2 分鐘 | 0 |
| LINE 回覆 | Reply API 不計入訊息額度 [6] | 只用 reply，不用 push | 0 |

要注意的地方：

- Neon 的 compute 要固定 0.25 CU。若讓它 autoscale 到 2 CU，100 CU-小時很快用完；用完時 compute 會暫停到下個計費週期（不刪資料）[2]。
- Cloud Run 預設的 request-based 計費下，回應送出後 CPU 會被節流，閒置不收費 [1]。
- Cloud Run（台灣）與 Neon（新加坡）跨雲的實際延遲尚未實測。

來源（查核於 2026-10-20／21）：
[1] <https://cloud.google.com/run/pricing>、<https://docs.cloud.google.com/run/docs/configuring/min-instances>　
[2] <https://neon.com/pricing>、<https://neon.com/docs/introduction/scale-to-zero>　
[3] <https://cloud.google.com/secret-manager/pricing>　
[4] <https://cloud.google.com/artifact-registry/pricing>　
[5] <https://cloud.google.com/build/pricing>　
[6] <https://developers.line.biz/en/docs/messaging-api/pricing/>

### 給 LINE webhook（ticket 12）的注意事項

service 用 `--cpu-throttling`（request-based 計費）：**HTTP 回應送出後 CPU 就被節流**，背景工作可能跑不完。所以 webhook 必須在回應 LINE 之前做完整個流程（下載檔案、`process_upload`、用 reply token 回覆），再回 200；不要用 FastAPI `BackgroundTasks` 或先回 200 再處理。reply token 本來就只有 1 分鐘有效，同步處理也剛好配合。service 的請求逾時設為 60 秒。

### Neon 連線為什麼用直連

Neon 的 pooled endpoint（PgBouncer transaction mode）不適合跑 migration [Neon connection pooling 文件](https://neon.com/docs/connect/connection-pooling)。app 最多 2 個執行個體，每個 SQLAlchemy pool 最多 15 條連線，共 30 條，遠低於 0.25 CU 的 104 條上限，所以 app 和 migration 共用一條直連字串就夠了。
