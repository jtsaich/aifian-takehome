# 13: 文件三份初稿

**What to build:** 照三輪設計拷問的結果改寫需求文件，再寫出交付規定的兩份文件初稿：給老闆的一頁說明和設計說明。這兩份由 agent 先寫，Jack 之後自己補。拷問紀錄在 vault 的專案資料夾（grill-round-1 到 3），事實查證在同一個資料夾的 research。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 改寫需求文件，把第一輪 Q1–Q12、第二輪 R1–R14、第三輪 S1–S9 的定案都寫進去。已經推翻的內容要刪掉：快照比對、取貨門市欄、push 通知、POS 對帳。
- [x] 給老闆的一頁說明：繁中、不用技術語言、一頁以內，寫清楚四件事：
  - 第一週他會拿到什麼
  - 要他和 POS 廠商配合什麼
  - 用什麼指標判斷成功
  - 看到什麼結果就停下來
- [x] 設計說明（繁中）要包含：
  - 核心問題和關鍵假設
  - MVP 怎麼切、刻意不做什麼，以及原因
  - 技術選型：自建，還是用 Ragic、Google Sheets、Airtable、WiXtar；數字要引用 research 裡查到的資料
  - 接下來 2–6 週的推進：在 POS 開一個獨立的喜餅取貨品項、處理門市現場購買的客人、建立會員同意加入的流程
  - 第一次跟老闆和 POS 廠商開會要問的問題：會員的三個問題、修改截止點、群組裡是不是已經有別的 bot、喜餅取貨有沒有走 POS、個資的目的外利用
  - operation 的建議：編號訂購單、傳檔規則、待確認的處理 SOP、新舊流程並行期、記錄差點出錯（near-miss）的情況
- [x] 設計說明裡加一節「如果答案是 X，我會改 Y」。
- [x] 需要 Jack 補的地方，用明確的標記標出來。
- [x] 繁中的部分寫完，用 humanizer-zh-tw 潤稿。
- [x] 設計說明可以匯出成 PDF。

## Comments

- 2026-10-21：在 integration branch `mvp` 完成（merge 10a121e），code review 修正見 merge「Merge code review fixes」。
