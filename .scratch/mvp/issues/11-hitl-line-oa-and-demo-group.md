# 11: [HITL] 建 LINE OA 與 demo 群組

**What to build:** 把 demo 要用的 LINE 官方帳號和群組準備好。這張要 Jack 本人登入 LINE 的後台操作。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 建好 Messaging API channel，方案用免費的輕用量。
- [x] 在 Developers Console 打開「允許加入群組」。這個設定預設是關的。
- [x] 關掉自動回覆和加好友歡迎訊息，免得 demo 時被干擾。
- [x] 建好 demo 群組，成員代表六家門市加上廚房，可以用幾個測試帳號充當，然後把 OA 加進群組。
- [x] 把 channel secret 和 access token 放進部署環境的 secrets，不要放進 repo。
- [x] 記下 webhook URL 要填在哪裡，等 12 部署完成後再填入。

## Comments

- 2026-10-21：Jack 建好 OA、channel 與 demo 群組，本機用 ngrok 接通。金鑰目前在本機 `.env`；部署時由 `scripts/deploy.sh` 存進 Secret Manager（ticket 03）。
