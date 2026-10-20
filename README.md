# 喜餅訂單匯流

門市照舊用 Excel 記喜餅訂單，把檔案傳進有中央廚房 LINE OA 的群組；後端保存原檔、合併成總表，並回覆傳檔的人。

## 本機啟動

需要 Docker。一個指令把 app 和 Postgres 一起啟動：

```sh
docker compose up --build
```

開 <http://localhost:8000>：

- 總表：`/orders`，可以依門市和取貨日篩選。
- 上傳紀錄：`/uploads`，每一份原檔都可以下載。
- 模擬群組上傳：`/demo/upload`（demo 用，門市不會看到）。選一位傳檔者、上傳 `mock_data/` 裡的檔案，畫面上的回覆就是 LINE 群組會收到的內容。

## 開發

```sh
uv sync
uv run pytest   # 需要 Docker（testcontainers 會起一個 Postgres）
```
