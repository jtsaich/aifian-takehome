# 15: [HITL] 錄 demo 影片、邀出題方進群組

**What to build:** 用真的 LINE 群組把 14 的劇本完整錄一次，再把群組準備好，讓出題方可以加入自己試。

**Blocked by:** 12（LINE OA 接入與門市綁定）、14（Demo 腳本與 README）

**Status:** resolved

- [x] 錄完 14 的劇本（改為自動錄製線上版網頁，見 Comments）。
- [x] 影片長度控制在 5 分鐘以內（2 分 45 秒）。
- [ ] 準備好群組的邀請連結（未做：交件改以線上網址＋影片呈現）。
- [x] 影片連結寫進 README。

## Comments

- 2026-10-22：影片用 Playwright 直接操作線上版（Cloud Run）錄製，畫面加繁中字幕、沒有旁白、沒有手機畫面；模擬群組上傳頁的回覆與 LINE 群組相同。影片在 https://bakery-orders-design.jtsai0606.workers.dev/demo.mp4（原檔 `docs/media/demo.mp4`，gitignored）。沒有提供 LINE 群組邀請連結。2026-10-22 已交件。
