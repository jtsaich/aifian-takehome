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

`bakery-init`（容器啟動時會跑）會建好這幾個帳號，密碼都是 `demo1234`：

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
