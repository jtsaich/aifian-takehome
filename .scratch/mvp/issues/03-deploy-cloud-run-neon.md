# 03: 部署到 Cloud Run＋Neon

**What to build:** 把 02 的流程部署到公開的 HTTPS 網址上，並確認跑得通。之後每張 ticket 完成後，都能直接部署到這裡驗收。

**Blocked by:** 02（骨架：模擬群組上傳 → 總表）

**Status:** ready-for-human

- [x] 跑在 Cloud Run 的 asia-east1 區域，最少執行個體數設為 0；資料庫用 Neon，連線走 TLS。
- [x] 原檔要存在持久的地方，不能存在容器本機的磁碟上，因為容器重新啟動，本機檔案就會消失。
- [x] secrets 不進 repo。
- [x] 一個指令就能部署。
- [x] README 寫下部署步驟，以及每月成本估算（目標是落在免費額度內）。
- [ ] 在公開網址上用 02 的流程上傳一次，確認成功。

## Comments

- 2026-10-21：程式與測試在 `mvp` 完成（merge 26ff00e）。剩下的實機驗收需要 Jack 的帳號（見 README 部署與 LINE 章節），所以改成 ready-for-human。
