# aifian-takehome

FDE take-home：模擬一家老字號糕餅連鎖的真實案子。門市照舊用 Excel 記喜餅訂單，只是把檔案改傳到中央廚房的 LINE OA；後端自動合併總表、做稽核、產生廚房生產彙總，並以電話為 ID 建立客人資料。
需求在 `docs/requirements/requirements.md`（**v0 草案，Jack 核准前不寫程式**）。題目原文與計畫在 `~/ootobai/vault/scratch-pad/AIFIAN.md`、`~/ootobai/vault/projects/aifian-takehome/plan.md`。

Stack：Python＋FastAPI＋Postgres。交付形式：repo＋demo 影片，期限 2–3 天。

## 硬約束

- **門市端沒有新介面。** 門市只會碰到 Excel 範本和 LINE。不要加任何需要門市人員登入或填寫的表單。
- **處理流程不用 LLM。** 解析、檢查、合併、比對差異都用確定的規則。
- **每一份上傳都要回覆。** 成功、部分錯誤、拒收都要回覆傳檔的人；不能有傳了沒回應的檔案。
- 原檔和差異紀錄只增不改（append-only）。
- LINE 只用 reply 回覆，不用 push（push 會吃推播額度）。webhook 依 `webhookEventId` 去重。
- 只用模擬資料。log 不寫入姓名和電話。
- 這是對外的作品：README、commit message 不提面試流程，也不寫公司內部資訊。
