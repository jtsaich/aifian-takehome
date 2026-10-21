---
title: 會員：預設做法與行銷要追的數字
---

本文展開 `docs/design.md` 第 4–6 週的會員。每一項都是預設，要跟客戶的行銷部門確認；問題已用 email 提出，沒有回覆也照預設往下做。方括號是第 8 節的來源編號（查證日 2026-10-21）；查不到的標「未查證」，推論標「推論」。法規部分是非律師的判讀，要請客戶的律師確認。

## 1. 為什麼會員排在第 4–6 週，第一週先做什麼

會員要回答哪位客人在什麼時候買了什麼。資料來源有兩個：喜餅訂單有客人電話和金額，但散在六家門市格式不同的 Excel；POS 每晚的 CSV 是「日 × 店 × 品項」的彙總，記不到客人，也沒有收據號和時間。所以第一週先把喜餅訂單和客人電話整理成一份資料，同時向 POS 廠商提出三項需求（廠商改功能要一個月以上）：結帳時記下會員手機或 LINE 會員條碼並寫進每晚的 CSV；CSV 改成逐筆交易，帶收據號、交易時間、門市代碼、會員識別（原因見第 5 節）；另開「喜餅訂單取貨」品項並填單號。廠商改好之前，會員先走不需要 POS 的 A 階段（第 4.1 節）。

## 2. 先問行銷部門：他們想拿到什麼

每天要用會員資料的是行銷部門，第一次開會先找行銷。**痛點假設（待驗證）**：廣告和貼文只看得到曝光、點擊，看不到有沒有帶來喜餅訂單或門市消費；喜餅客人買完一次就斷了聯絡，之後的彌月、中秋禮盒有沒有回來買，沒人知道；發訊息只能全體群發，挑不了時間和對象。

**要問的問題**（與 email 第 5–7 題一致，design.md 第 5 節「問行銷部門」列成會議題目）：會員 App 要解決的是回頭客、新客、推播還是品牌形象？現在投哪些廣告、看哪些數字？有了會員最想知道什麼？現在有多少 LINE 好友、發過簡訊或 EDM 嗎？舊喜餅訂單有沒有留電話？點數、生日禮、等級哪些是一定要有的？

**行銷要追的漏斗**（業界通用定義；最後一欄對應第 5 節的資料階段）：

| 階段 | 指標 | 需要的資料 | 何時算得出來 |
|------|----------------|----------------|------|
| 廣告／管道 → 會員 | 各入會來源的新會員數 | 每店、每檔活動一組加好友 QR 或網址 [24]，網頁註冊帶 UTM [27]，來源存進會員主檔 | 有 LINE 好友 |
| 會員 → 首購 | 入會後 N 天內有消費的會員 ÷ 新會員 | 入會日、帶會員識別的交易 | POS 記會員 |
| 首購 → 回購 | 期間內消費 2 次以上的會員 ÷ 有消費的會員 | 同上，有收據號才算得準「一次」 | POS 記會員 |
| 回購 → 忠誠 | 入會月 cohort 留存、RFM 分層、營收型 LTV | 同上 | POS 記會員 |
| 訊息 → 購買 | 收到訊息者 X 天內消費比例，對比沒收到的對照組 | LINE userId 對到會員 | POS 記會員 |
| 廣告 → 門市營收 | 某支 Meta／Google 廣告帶來的門市營收 | 逐筆交易加會員手機，回傳廣告平台 | 接轉換 API |
| 喜餅客 → 彌月／節慶 | 喜餅客之後買彌月、中秋禮盒的比例與間隔 | 同一支電話的喜餅單與後續訂單 | 有舊訂單電話就能先算 |

**發訊息的時間點**：郭元益建議婚期前 2–3 個月訂餅 [2]；金格的彌月試吃資格是「媽媽手冊產檢頁 28 週以上，或寶寶出生證明 1 個月內」[6]。喜餅到彌月隔多久沒有品牌寫，先假設婚後 1–3 年，用客戶自己的訂單驗證。結婚週年禮在查到的品牌裡沒有一家當成產品線，先看資料有沒有自然的回購高峰。

## 3. 大品牌怎麼做

查了 9 個喜餅／烘焙品牌和 3 個參考品牌的會員條款 [1]–[13]。下表列其中 8 個，其餘只進計數；例如大黑松沒有點數，只發官網購物金 [3]，85度C 的累點規則只在 App 裡，查不到 [11]。

| 品牌 | 門市怎麼認會員 | 回饋率／效期 | 喜餅、彌月相關 |
|------|-----------|-----------|-----------|
| 郭元益 [1] | 未載明，查點要報姓名手機 | 1%／一年內用完 | 會員憑媽媽手冊免費領彌月禮盒 |
| 禮坊 [5]、糖村 [7] | 官網限定，門市不通用 | 1%，每筆折抵上限 10%／禮坊 365 天，糖村次年年底 | 官網喜餅訂單沒有排除累點 |
| 金格 [6] | 官網限定 | 無點數，註冊送 $100 | 喜餅／彌月試吃盒 85 折，限一次 |
| 一之軒 [8] | LINE 官方帳號會員卡 | 2%／365 天 | 未載明 |
| 新東陽 [10] | App 電子卡；快速註冊者可報手機累點，折抵要出示電子卡 | 約 0.33%／翌年 12/31 | 不適用 |
| 伊莎貝爾 [4] | 未載明 | 未查證 | 婚禮季喜餅淨額每滿 1 萬送 $500；喜餅、彌月同一檔活動 |
| 全聯 [13] | 卡片或 App QR；折抵不接受報電話 | 0.3%／消費點數無期限 | 不適用 |

12 個品牌的計數：

- **門市辨識**：3/9 喜餅烘焙品牌明文寫官網會員不通用門市；出示 App 條碼或綁定電子卡 5/12；LINE 會員卡 1/12；明文允許報手機累點 1/12，明文拒絕電話折抵 1/12；讓客人掃門市 QR 累點 0/12。
- **點數**：10/12 有點數；寫明回饋率的 7 個裡，2% 有 1 個、1% 有 3 個、約 0.3% 有 3 個。效期寫明的 9 個中，取得後滾動一年 3 個，按年度固定日到期 3 個。
- **等級** 7/12，寫明門檻的 4 個都看年度消費額；**生日禮** 8/12，5 個是購物金或折價券；**行銷管道**：LINE 官方帳號 8/12、App 5/12、Email 4/12、簡訊 2/12。
- **喜餅**：會員條款專門處理喜餅累點的 0/9。把喜餅和彌月連起來的只有伊莎貝爾的限期活動（對象寫明「準新人」和「準爸媽」）[4] 和郭元益的全體會員彌月福利 [1]，沒有一家把「買過喜餅」自動接到之後的彌月權益。

## 4. 預設做法

### 4.1 門市怎麼認出會員

- **A 階段（第 4–5 週，POS 未改）**：客人取貨或結帳時掃門市 QR，加入 LINE 官方帳號、開 LINE 會員卡、勾選同意後成為會員。喜餅訂單的點數由總部依訂單資料在會員後台發放；門市日常消費這階段不給點。店員只需要指一下 QR。
- **B 階段（POS 逐筆記下會員）**：客人報手機或出示會員卡條碼，店員在 POS 多輸入一欄；每晚 CSV 進來後依會員識別發點，隔天入帳。郭元益首購點數 5 個工作日後才能用 [1]，糖村取貨 2 天後才發點 [7]，隔天入帳可以接受。
- **工具**：A 階段用 LINE 幫手市集的 EchossVIP Lite：中／高用量方案下免費版 0 元，付費版每月 NT$630（含稅），有會員卡、入會禮、生日禮、後台發點扣點 [15]。Lite 只能手動發點；B 階段依 CSV 自動發點，要用 Echoss VIP 標準版 API（價格未公開）或我們自己記點數，第 6 週決定。
- **報手機可以累點，折抵要出示會員卡**，同新東陽 [10]。全聯折抵不接受報電話 [13]；折抵等於付錢，只靠一支電話容易被冒用。
- **不採用**：LINE 原生集點卡沒有金額欄位、不接 POS，停用後客人的點數全部刪除 [14]；客人自己掃門市 QR 累點，12 個品牌沒有一家這樣做；實體卡新東陽已停發 [10]。

### 4.2 點數、等級、生日禮

- **累點**：每 100 元 1 點，1 點折 1 元（1%），同郭元益、禮坊、糖村 [1][5][7]；每筆最多折抵 10%，同禮坊、糖村。喜餅在付清尾款取貨後給點，訂金不給點、也不轉成點數（第 6 節）。
- **用途**：預設是下次消費折抵。喜餅相關的兩個提案，由行銷決定：喜餅客之後訂彌月禮盒享專屬折扣或試吃盒（參考郭元益 [1]、金格 [6]），這個權益掛在「喜餅客」身分上，因為婚後到彌月可能比點數效期還長；喜餅點數可換婚禮小物或伴手禮加購。
- **效期**：取得年度的次年 12/31 到期，同新東陽 [10]。一年結算一次，客人好記，每筆點數至少有 12 個月；到期前用 LINE 提醒。
- **不做儲值、不賣點數**：花錢買的點數屬於禮券，不能設期限，還要履約保障（第 6 節）。
- **等級第一階段不做**：A 階段算不出年度消費額，只看喜餅會讓每位喜餅客都落在最高級（推論）。B 階段有半年資料後，用 RFM 看會員自然分成幾群再決定。
- **生日禮做**：生日當月一張折價券，當月有效。金格、新東陽是 $100，禮坊是 $100 券滿 $1,000 可用 [5][6][10]，金額由行銷定。LINE 好友屬性沒有生日 [25]，要由會員工具在入會時收集 [15]。

### 4.3 後台：誰能動點數

門市只能發點（B 階段由系統自動）和核銷。手動加減點只開給總部行銷 1–2 人，每次填原因，系統記下誰、何時、改多少，每月看一次清單。退貨連帶扣點，全聯條款有這一條 [13]。每月報表看各來源新會員、發點、扣點、發券、核銷，EchossVIP Lite 有這些統計 [15]。會員主檔分 LINE、簡訊、Email 記行銷同意，退訂立即生效。

### 4.4 行銷管道

**先做 LINE 官方帳號。** 「加入好友管道」可以設管道、來源、活動名稱，各自產生 QR 或網址，後台看得到各管道的好友數 [24]。預設每家門市、每檔廣告、每張 DM 各一組，第一個月就看得出哪個管道帶來會員。漸進式訊息可依加好友或受眾觸發，每步間隔 1–30 天、最多 50 步 [26]，用在喜餅訂單後的近期提醒；彌月這種跨年提醒由我們自己排程發送。

**之後再加**：沒加 LINE 的客人用簡訊補，Email 當備援。喜餅取貨、出貨通知可用 LINE 通知型訊息，有手機號碼就能發，但不能發廣告促銷，要藍盾或綠盾帳號和自建後台 [17]。App 推播要等第 6 週決定做 App。

3,000 名會員、每人每月 4 則（12,000 則）的發送成本，不含系統、人力、App 開發；美元以 1:32 換算：

| 通路 | 月成本 | 限制 |
|------|-------------|----------|
| LINE OA 高用量 [16] | 月費 1,400 元含 6,000 則，超出的 6,000 則 × 0.2 元，共 2,600 元（未稅）；中用量只有 3,000 則且不能加購 | 只送得到好友；會員卡另計 0 或 630 元 [15] |
| LINE 通知型訊息 [17] | 12,000 × 0.2 = 2,400 元 | 不能發行銷內容 |
| 簡訊 EVERY8D [18] | 12,000 × 0.81 = 9,720 元（含稅） | 70 字內算 1 則，71–134 字算 2 則 |
| 簡訊 三竹 [19] | 「0.7 元起」，至少 8,400 元 | 級距未公開 |
| Email Brevo Starter [20] | US$9 + US$23 ≈ 1,024 元 | 要先有 email；級距加價方式是推論，下單前確認 |
| App 推播 FCM [21][22][23] | 0 元；Apple 年費 99 USD（約 264 元／月），Google 一次 25 USD | 開發維護費未查證，是最大的一項 |

## 5. 行銷在每個資料階段能回答什麼

| 問題 | 今天 | 有 LINE 好友＋手機 | POS 記下會員 | 接上轉換 API |
|----------|----|----|----|----|
| 哪個廣告、海報、門市帶來會員 | 不行 | 可以 | 可以 | 可以 |
| 新會員有沒有首購；回購率、留存、RFM | 不行 | 不行 | 可以 | 可以 |
| 喜餅客之後有沒有買彌月、節慶禮盒 | 只靠舊訂單電話 | 限留了電話的喜餅單 | 可以 | 可以 |
| 發訊息後有沒有來店 | 不行 | 只看開啟、點擊 | 可以，對比對照組 | 可以 |
| 挑對象發訊息（例：90 天沒來） | 不行 | 只能依管道、標籤 | 可以 | 可以 |
| 哪支 Meta／Google 廣告帶來門市營收 | 不行 | 不行 | 不行 | 可以 |
| 會員 LTV 對比各管道獲客成本 | 不行 | 不行 | 只有營收型 LTV | 可以 |

最後一欄要把門市交易回傳廣告平台，三家都接受雜湊後的手機號碼。Meta 門市事件用 `action_source: physical_store`，可帶門市代碼和收據號（`order_id`，去重用），事件時間不能早於 7 天前 [29]。Google store sales 只開放 allowlist 帳號，要幾百筆以上交易 [31]，這家公司能不能進未查證；喜餅試吃預約若放在網頁，可改用 enhanced conversions for leads [30]。LINE Conversion API 文件只看得到網站事件，能否歸因門市消費未查證 [28]。有同意的會員手機也能上傳 Google Customer Match 當廣告受眾 [32]。

所以 POS 每筆交易至少要有**收據號、交易時間、門市代碼、會員手機（或對得回手機的會員 id）**，也就是第一週送給廠商的需求。

## 6. 個資與點數的法規預設

以下是解讀，並非法律意見，客戶的律師確認後才寫進條款。

- **入會**：依個資法 §8 告知公司名稱、目的、資料類別、利用期間地區對象方式、當事人權利、不提供的影響，資料交給會員工具或簡訊商也要寫進去；行銷同意依管道分開勾選，紀錄要留，因為 §7 第 4 項把舉證責任放在業者 [33]。
- **舊喜餅訂單的電話**是為履行訂單蒐集（§19 第 1 項第 2 款），拿來行銷是特定目的外利用，需要 §20 第 1 項第 6 款的同意，而且依 §7 第 2 項要「單獨所為」，不能藏在訂購單小字裡 [33]。預設：舊電話只留在內部客人資料，不發行銷訊息，會員一律由客人自己加入。拿舊訂單在內部算喜餅客的回購，是否在原目的之內，也請律師確認。
- **每則行銷訊息**：首次行銷就提供拒絕方式並由業者付費，客人拒絕後立即停止（§20 第 2、3 項）[33]。查不到專門規範商業簡訊的現行法律 [38]，簡訊、LINE、Email 都以 §20 為準。
- **免費點數和券可以設期限**：禮券事項排除「發行人無償發行之抵用券、折扣（價）券」[34]，消保處出版品也說會員卡加送的點數不在禮券規範內 [35]。期限寫進條款，券面標「贈品券、不可兌現、有效期限」。
- **花錢買的點數或儲值屬於禮券**：不得記載使用期限，要有至少一年的履約保障 [34][35]；能在別家店用的儲值只有電子支付機構能做 [36]。第一階段不做。烘焙業禮券的主管機關可能是衛福部或經濟部，請律師確認 [34]。
- **喜餅訂金維持民法定金性質**（§248–249）[37]，不開可轉讓的提貨券，也不轉成儲值或點數。

## 7. 第 6 週要不要做 App 的判斷條件

至少符合一項，才去詢 App 開發報價：

1. 行銷列得出 LINE 會員卡做不到、又有營收理由的功能，例如線上訂喜餅查進度、行動支付或儲值（儲值帶來第 6 節的禮券義務）。
2. LINE 訊息費用大到值得換：會員 10,000 人、每月 4 則，高用量約 1,400 + 34,000 × 0.2 = 8,200 元／月（未稅）[16]，拿去跟 App 報價比。
3. 老闆的目標是自有通路或品牌形象，而且接受門市推廣下載的人力。

符合任一項就先不做：POS 還沒逐筆記下會員，App 沒有消費紀錄可以顯示；或取貨時加入 LINE 會員的比例偏低，加好友比下載 App 少一步，LINE 都推不動，App 更難（推論）。參考品牌的 App 評分：亞尼克 1.8（357 則）[9]、85度C 2.4（662 則）[11]，評論多抱怨登入和驗證。

## 8. 參考來源

::: {style="font-size: 8pt; line-height: 1.35; overflow-wrap: anywhere"}
[1] 郭元益 會員權益 https://www.kuos.com/zh-TW/pages/membership-rights
[2] 郭元益 訂餅須知 https://www.kuos.com/zh-TW/pages/pastry-ordering-guidelines-and-traditional-ritual-information
[3] 大黑松小倆口 FAQ https://www.salico.com.tw/pages/faq
[4] 伊莎貝爾 https://www.isabelle.com.tw/welcome/news-detail/2026pearl0825/ 、https://www.isabelle.com.tw/welcome/news-detail/295
[5] 禮坊 https://store.rivon.com.tw/pages/rivonvip
[6] 金格 https://www.king.com.tw/pages/%E6%9C%83%E5%93%A1%E5%88%B6%E5%BA%A6 、https://www.king.com.tw/pages/faq-1
[7] 糖村 https://www.sugar.com.tw/pages/membership-level
[8] 一之軒 https://www.ijysheng.com/pages/%E6%9C%83%E5%93%A1%E6%AC%8A%E7%9B%8A
[9] 亞尼克 https://www.yannick.com.tw/yanright 、https://apps.apple.com/tw/app/%E4%BA%9E%E5%B0%BC%E5%85%8B%E9%9A%A8%E4%BA%AB%E5%8D%A1/id1265001179
[10] 新東陽 https://www.hty.com.tw/member-service.php 、https://www.hty.com.tw/member-level.php 、https://www.hty.com.tw/member-bonus.php
[11] 85度C https://apps.apple.com/tw/app/85-cafe/id1256367544
[12] 星巴克 https://www.starbucks.com.tw/rewards/level_benefit.jspx
[13] 全聯 https://www.pxmart.com.tw/customer-service/card/terms
[14] LINE 集點卡 https://tw.linebiz.com/manual/line-official-account/oa-manager-stampcard/ 、https://help2.line.me/official_account_tw/web/categoryId/20006394/pc?contentid=20014830&lang=en
[15] 幫手市集 https://tw.linebiz.com/column/oaplus-solutionshub-intro/ ；EchossVIP https://www.12cm.com.tw/oa-plus-crm/ 、https://www.12cm.com.tw/echoss-vip/
[16] LINE OA 2026 方案 https://tw.linebiz.com/column/LINEOA-2026-Price-Plan/ 、https://tw.linebiz.com/faq/shop-oa/shop341/
[17] LINE 通知型訊息 https://tw.linebiz.com/service/account-solutions/line-notification-message/
[18] EVERY8D https://www.teamplus.tech/product/every8d-price/
[19] 三竹 https://sms.mitake.com.tw/
[20] Brevo https://www.brevo.com/pricing/
[21] Apple Developer https://developer.apple.com/help/account/membership/program-enrollment/
[22] Google Play https://support.google.com/googleplay/android-developer/answer/6112435?hl=en
[23] Firebase https://firebase.google.com/pricing
[24] LINE 加入好友管道 https://tw.linebiz.com/manual/line-official-account/oa-manager-addfriend/
[25] LINE 分眾 https://tw.linebiz.com/column/line-oa-segement-marketing/
[26] LINE 漸進式訊息 https://tw.linebiz.com/manual/line-official-account/oa-step-message/
[27] GA4 UTM https://support.google.com/analytics/answer/10917952?hl=en
[28] LINE Conversion API https://conversion-api-docs.linebiz.com/en
[29] Meta 離線事件 https://developers.facebook.com/docs/marketing-api/conversions-api/offline-events
[30] Google enhanced conversions https://support.google.com/google-ads/answer/9888656?hl=en
[31] Google store sales https://developers.google.com/google-ads/api/docs/conversions/upload-store-sales-transactions 、https://support.google.com/google-ads/answer/10018336?hl=en
[32] Google Customer Match https://support.google.com/google-ads/answer/6379332?hl=en
[33] 個人資料保護法 https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=I0050021
[34] 禮券定型化契約應記載及不得記載事項：經濟部 https://law.moea.gov.tw/LawContent.aspx?id=GL000996 （未能開啟）；全文轉載 https://citytourism.chcg.gov.tw/getFile.aspx?did=22458&file=2&file_id=306974&type=2
[35] 行政院消保處〈禮券消費者權益之探討〉 https://cpc.ey.gov.tw/File/58FBB3FDEC7BD56C?A=C
[36] 電子支付機構管理條例 https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=G0380237
[37] 民法 https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=B0000001
[38] 全國法規資料庫查詢 https://law.moj.gov.tw/Law/LawSearchResult.aspx?ty=ONEBAR&kw=濫發商業電子郵件
:::
