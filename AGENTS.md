# aifian-takehome

FDE take-home：模擬一家老字號糕餅連鎖的真實案子。門市照舊用 Excel 記喜餅訂單，只是把檔案改傳到中央廚房的 LINE OA；後端自動合併總表、做稽核、產生廚房生產彙總，並以電話為 ID 建立客人資料。
實作依據是 `.scratch/mvp/issues/` 的 ticket、`GLOSSARY.md`、`docs/adr/`；實作共用筆記在 `~/ootobai/vault/projects/aifian-takehome/impl-notes/architecture.md`。`docs/requirements/requirements.md` 由 ticket 13 改寫，改寫前以 ticket 為準。題目原文與計畫在 `~/ootobai/vault/scratch-pad/AIFIAN.md`、`~/ootobai/vault/projects/aifian-takehome/plan.md`。

Stack：Python＋FastAPI＋Postgres。交付形式：repo＋demo 影片，期限 2–3 天。

## 硬約束

- **門市端沒有新介面。** 門市只會碰到 Excel 範本和 LINE。不要加任何需要門市人員登入或填寫的表單。
- **處理流程不用 LLM。** 解析、檢查、合併、比對差異都用確定的規則。
- **每一份上傳都要回覆。** 成功、部分錯誤、拒收都要回覆傳檔的人；不能有傳了沒回應的檔案。
- 原檔和差異紀錄只增不改（append-only）。
- LINE 只用 reply 回覆，不用 push（push 會吃推播額度）。webhook 依 `webhookEventId` 去重。
- 只用模擬資料。log 不寫入姓名和電話。
- 這是對外的作品：README、commit message 不提面試流程，也不寫公司內部資訊。

## Agent skills

### Issue tracker

Tickets live as local markdown under `.scratch/<feature>/issues/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` + `docs/adr/`. See `docs/agents/domain.md`.

## 常用指令

- 安裝：`uv sync`
- 本機啟動（app＋Postgres）：`docker compose up --build`，開 http://localhost:8000 。容器啟動時先跑 `bakery-init`（Alembic 升到 head＋種入門市、品項、demo 傳檔者，可重跑）。
- 測試：`uv run pytest`（需要 Docker：testcontainers 每次測試起一個 Postgres）
- 新增 migration（歷史保持線性，一張 ticket 一個）：`DATABASE_URL=... uv run alembic revision --autogenerate --rev-id 000N -m "<slug>"`，產生後要人工檢查。
- 重新產生範本、模擬檔與對照表（輸出到 `mock_data/`，預設第一天＝台北時間今天）：`uv run generate-mock-data [--today YYYY-MM-DD] [--seed N]`。repo 裡的 `mock_data/` 是以 `mock_data/expectations.json` 記錄的 seed 與日期產生的快照，測試會檢查它跟產生器一致；改了產生器就用同一個日期重跑一次再 commit。
