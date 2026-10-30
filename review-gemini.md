# PoC 工單分類結果檢討與分類制度（Taxonomy）重構提案

本文件針對 [note.md](file:///Users/james/projects/playground-fde/note.md) 所提出的 9 筆工單分類疑問，結合 [sample_tickets.csv](file:///Users/james/projects/playground-fde/poc/data/sample_tickets.csv)、[expected_labels.csv](file:///Users/james/projects/playground-fde/poc/data/expected_labels.csv) 與最新執行結果 [triage_result.csv](file:///Users/james/projects/playground-fde/poc/output/triage_result.csv) 進行根因診斷，並提出調整後的分類制度（主類別、細項、預設 `route` 與 `priority`）。

---

## 一、 逐筆檢視 `note.md` 的 9 筆工單問題與診斷

### 1. `TK-1004`：打電話 40 分鐘沒人接！（同時詢問行程表何時寄來）
* **工單原文**：「你們客服電話是裝飾品嗎？等了 40 分鐘沒人接，這是什麼服務態度！！我只是要問行程表什麼時候寄來而已。」
* **現況設定**：`complaint / pure_complaint` | `priority = P2` | `route = auto`
* **您的反饋**：這應該是要真人處理，服務品質差；另外他是有問行程表。
* **問題根源與修正建議**：
  1. **為何不該走 `auto`**：原設計假設「未要求賠償的純抱怨」可用 AI 致歉草稿（`auto`）處理。但實務上客戶已因電話打不通產生強烈情緒（「這是什麼服務態度！！」），且帶有複合訴求（查詢特定訂單之行程表寄送進度）。這類服務品質抱怨若未經真人優先安撫與查單，極易演變成升級客訴。
  2. **修正做法**：將 `complaint` 下的 `pure_complaint` 更名為 **`service_or_channel_complaint`（服務品質與通道抱怨）**，並將其預設分流由 `auto` **改為 `human`**（涵蓋 `TK-1004`、`TK-1024`）。如此一來，**整個 `complaint`（客訴與抱怨）大類 100% 強制由真人接手（`route = human`）**；針對 `TK-1004` 附帶的「行程表何時寄出」詢問，系統於內部輔助摘要中附上訂單與行前通知規則供真人一併回覆。

---

### 2. `TK-1006`：詢問企業包團服務（120 人年度員工旅遊）
* **工單原文**：「您好，我們公司約 120 人想辦年度員工旅遊，貴公司有企業包團的服務與報價窗口嗎？」
* **現況設定**：`other_non_cs / b2b_media_hr_referral` | `priority = P1` | `route = human`
* **您的反饋**：詢問企業包團服務，可能算是客製化行程，分類應該要改，算是客服，我覺得是 `P2`。
* **問題根源與修正建議**：
  1. **為何原分類不合理**：120 人企業包團是**高單價的買方客戶旅遊需求**，本質上是向客服/業務詢問「團體客製化包團行程與報價」，不應與「遊覽車供應商報價、求職履歷、KOL 業配」一起被當成 `other_non_cs`（非客服 `P1` 墊底雜訊）。
  2. **修正做法**：
     * 改歸入 **`product_inquiry / customization_request`（售前產品詢問 — 客製化與企業包團需求）**。
     * `priority` 由 `P1` 調升為 **`P2`（一般標準優先）**，`route = human`（由真人客服或專責團控業務接手報價）。

---

### 3. `TK-1009`：郵輪艙房可否指定樓層
* **工單原文**：「預訂了 9 月的沖繩郵輪行程，海景艙可以指定高樓層或船中段嗎？會暈船所以想避開船頭。」
* **現況設定**：`product_inquiry / customization_request` | `priority = P2` | `route = human`
* **您的反饋**：這是產品詢問，不應該客製化。
* **問題根源與修正建議**：
  1. **為何原分類不合理**：詢問「郵輪海景艙能不能指定高樓層或船中段」屬於**郵輪產品本身的艙等選位規則說明**（知識庫常見 QA），並非需要人工向供應商專案洽談的特殊客製化需求（如 `TK-1006` 企業包團、`TK-1022` 全素食機上與團體餐安排、`TK-1032` 輪椅斜坡巴士無障礙評估）。
  2. **修正做法**：
     * 改歸入 **`product_inquiry / product_spec_and_price`（售前產品詢問 — 規格與費用說明）**。
     * `priority = P2`，預設 **`route = auto`**（由 AI 檢索郵輪選位規定生成回覆草稿）。

---

### 4. `TK-1010`：發票統編打錯要重開（連動檢視 `TK-1039` 二聯改三聯發票）
* **工單原文**：「上週的訂單發票統編打成 12345677，正確應為 12345678，公司報帳被退件，麻煩重開，急。」
* **現況設定**：`order_info / document_and_invoice` | `priority = P2` | `route = auto`
* **您的反饋**：算是系統錯誤修正（或訂單資料/發票修正），如果沒有這個類別可能要 add or update。
* **問題根源與修正建議**：
  1. **為何原分類與分流不合理**：原設計將「沒收到確認信（`TK-1001`）」、「詢問能否開英文收據及需哪些資訊（`TK-1046`）」與「**已開發票統編打錯要求作廢重開（`TK-1010`）**」、「**已開二聯式要求改開三聯式發票（`TK-1039`）**」全部混在 `order_info / document_and_invoice` 並設為 `auto`。但「修改已開立發票統編／改開三聯式發票」涉及帳務系統作廢與重開作業，AI 唯讀查詢無法替客人修改，必須由真人操作處理（`route = human`）。
  2. **修正做法**：
     * 在 `order_change`（訂單修改與資料更正）底下，將原 `passenger_or_addon_change` 拆分為語意更精確的兩個細項（或擴充定義）：
       * **`order_change / data_or_invoice_correction`（旅客資料與發票統編更正，預設 `route = human`）**：專門涵蓋已成立訂單之資料修正，包含「發票統編打錯重開（`TK-1010`）」、「二聯式改開三聯式發票（`TK-1039`）」、「護照英文姓名拼音錯誤更正（`TK-1028`）」。
       * **`order_change / schedule_or_addon_change`（改期、團體異動與加購申請，預設 `route = human`）**：涵蓋改期（`TK-1007`）、改接送飯店（`TK-1012`）、團體部分退團（`TK-1043`）、加購嬰兒票（`TK-1005`）與加購行李（`TK-1045`）。
     * 原 `order_info / document_and_invoice` 則單純保留給**「訂單確認信／電子憑證查詢與收據規範詢問」**（`TK-1001`、`TK-1042`、`TK-1046`）。

---

### 5. `TK-1014`：合掌村冬季會因大雪取消嗎（為何被誤判為 `human`？）
* **工單原文**：「想訂 1 月的合掌村點燈行程，如果大雪導致巴士停駛，行程會取消嗎？取消的話怎麼退？」
* **現況執行結果**：模型選出 `product_inquiry / product_spec_and_price`，但信心分數僅 **`0.4708`（`< 0.70`）**，遭低信心門檻攔截轉為 `route = human`（成為全場唯一 1 筆分流錯誤）。
* **您的反饋**：這個應該是 `auto`，分析錯誤。
* **問題根源與修正建議**：
  1. **為何模型信心只有 `0.4708`**：因為 `TK-1014` 問的是「**大雪導致巴士停駛會不會取消？取消的話怎麼退？**」，本質上是**「旅遊規則與天候退改通則詢問」**，而不是「產品規格與費用（`product_spec_and_price`）」。當我們硬把 `TK-1014` 塞在 `product_spec_and_price` 時，模型在 `product_spec_and_price`、`policy_and_regulation` 與 `order_policy_and_refund_status` 之間猶豫不決，導致信心掉到 `0.47`！
  2. **修正做法（與下方 `TK-1021` 完美呼應）**：
     * 將 `product_inquiry / policy_and_regulation` 明確定義為 **「旅遊法規、簽證與天候不可抗力通則（預設 `route = auto`）」**，涵蓋護照效期（`TK-1018`）、簽證規定（`TK-1040`）與天候大雪/颱風停駛及退費通則（`TK-1014`、`TK-1021`）。
     * 如此一來，`TK-1014` 歸入 `product_inquiry / policy_and_regulation`，語意完全吻合，模型信心即可高於 `0.70` 並正確走 **`route = auto`**。

---

### 6. `TK-1021`：明天出發，颱風會不會延期？？
* **工單原文**：「我是明天 6/25 出發澎湖三日的旅客，氣象署發布海上颱風警報了，行程會延期還是照常？如果取消退費怎麼算？請今天務必回我！」
* **現況設定**：`order_refund / cancellation_refund_request` | `priority = P4` | `route = human`
* **您的反饋**：這比較像是旅遊規則詢問。
* **問題根源與修正建議**：
  1. **為何原分類不合理**：仔細看內文，旅客**尚未決定取消，也不是在申請退費**，而是在詢問「發布海上颱風警報後，行程會延期還是照常？若取消退費怎麼算？」。先前將其歸入 `order_refund`（申請取消退費）混淆了「詢問天災應變與退費規則」與「實際執行退單」。
  2. **修正做法**：
     * 與 `TK-1014` 一致，歸入旅遊規則/政策詢問（可歸入 **`product_inquiry / policy_and_regulation`** 或 **`order_info / order_policy_and_refund_status`**）。
     * **那為何它仍然是 `P4` 且 `route = human`？** 因為它的出發日是「明天（24 小時內）」，會同時命中 `urgent_level = high` 與硬性規則「72 小時內出發急件」，因此系統會自動將其優先級調升為 **`P4` 超重要**，並強制覆寫為 **`route = human`** 由真人緊急處理！這完美體現了「分類看問題本質（規則詢問）、分流與優先級看緊急程度（明日出發颱風 `P4/human`）」的解耦設計。

---

### 7. `TK-1016`（會員帳號被鎖）與 `TK-1030`（網頁價格與結帳金額不同）
* **工單原文**：
  * `TK-1016`：「連續輸錯密碼後帳號被鎖定，點忘記密碼也收不到簡訊驗證碼，裡面還有一筆待付款訂單，請協助解鎖。」
  * `TK-1030`：「官網寫大阪自由行 21,900 起，點進去選同樣日期結帳卻變 25,400，也沒有說明差在哪，這是標價錯誤還是系統問題？」
* **現況設定**：`order_info / account_and_pricing_issue` | `route = human`
* **您的反饋**：
  * `TK-1016`：帳號被鎖，現有分類好像不容易 cover，可能要加一個系統相關的大項。
  * `TK-1030`：這像是系統問題詢問，但是又有點抱怨的語氣，不太好分，但是不是 `order`。
* **問題根源與修正建議**：
  1. **為何原分類不合理**：這兩張單都不是在查詢既有訂單（`order_info`）。`TK-1016` 是「會員帳號鎖定與簡訊驗證碼系統異常」，`TK-1030` 是「前台網頁標價與結帳系統計算金額異常（尚未下單）」。硬塞在 `order_info` 底下確實名不副實。
  2. **修正做法 — 新增獨立主類別 `system_and_account`（系統與會員帳號問題）**：
     * 將原本寄生在 `order_info` 下的帳號與系統計價異常獨立出來，成為第 8 大類 **`system_and_account`**（預設 `route = human`），下設細項：
       * **`account_and_login_issue`（會員帳號與驗證碼異常）**：帳號鎖定無法登入、收不到簡訊驗證碼（`TK-1016`，因內有待付款訂單，`urgent_level = high` -> `P4 / human`）。
       * **`website_and_pricing_bug`（網站系統與結帳計價異常）**：官網標價與結帳系統跳價不符、結帳流程或頁面顯示異常（`TK-1030`，`P2 / human`）。

---

### 8. `TK-1017`：Re: 7月包車報價單（`other_non_cs` 細項調整）
* **工單原文**：「附上 7 月花東包車報價：45 人座每日 18,000 元含司機住宿，油資實報實銷。煩請確認後回傳簽回。」
* **現況設定**：`other_non_cs / b2b_media_hr_referral` | `priority = P1` | `route = human`
* **您的反饋**：這感覺是業務往來非客服，考慮在 `other_non_cs` 加入一個公司業務往來，`b2b_media_hr_referral` 或許要改名。
* **問題根源與修正建議**：
  1. 當 `TK-1006`（120人企業包團）移回客服的 `product_inquiry / customization_request` 後，`other_non_cs` 裡原本叫 `b2b_media_hr_referral` 的名稱確實容易讓人誤以為包含「B2B 企業客戶買團」。
  2. **修正做法**：將該細項更名為 **`business_pr_hr_referral`（公司業務往來與跨部門轉介）**（或拆分為 `business_and_vendor` 公司業務/供應商往來 ＋ `media_and_hr_referral` 媒體公關與人資應徵），明確涵蓋：
     * 供應商業務報價往來（`TK-1017` 巴士公司包車報價）
     * 外部行銷業配合作（`TK-1034` KOL 旅遊開箱提案）
     * 媒體公關採訪邀約（`TK-1047` 財經記者採訪）
     * 人資職缺應徵（`TK-1026` 應徵導遊職缺）

---

## 二、 調整前後之分類制度（Taxonomy）總覽對照

調整後共 **8 大主類別、16 個細項**（其中 **14 個模型分類選項** 參與 Stage 1 `stage=classification` 單階段選擇，嚴格維持 `< 20` 個選項限制；2 個為規則前置攔截 `precheck_only`）：

| 主類別 (`category`) | 細項 (`sub_category`) | 調整說明 | 預設 `route` | 對應樣本工單 (`48` 筆) |
| --- | --- | --- | :---: | --- |
| **1. `product_inquiry`**<br>（產品與旅遊規則詢問） | `product_spec_and_price`<br>（產品規格與費用說明） | 移入 `TK-1009`（郵輪指定樓層規定）；移出 `TK-1014`（改歸旅遊與天候規則） | `auto` | `TK-1003`, **`TK-1009`**, `TK-1025`, `TK-1036` |
| | `policy_and_regulation`<br>（旅遊法規、簽證與天候通則） | 明確涵蓋護照簽證規定，以及**天候不可抗力（大雪/颱風）停駛延期與退費通則詢問**（移入 `TK-1014`、`TK-1021`） | `auto`<br>*(註：急件或外部新法規由規則覆寫為 `human`)* | **`TK-1014`** (`auto`), `TK-1018` (`auto`), **`TK-1021`** (`P4/human`), `TK-1040` (`human`) |
| | `customization_request`<br>（客製化與企業包團需求） | 移入 **`TK-1006`（120人企業包團，`P2`）**；移出 `TK-1009` | `human` | **`TK-1006`**, `TK-1022`, `TK-1032` |
| **2. `order_info`**<br>（訂單與退改規定查詢） | `order_status_and_points`<br>（訂單進度與點數查詢） | 維持不變（查行程表/出發通知寄送時程、點數折抵規則） | `auto` | `TK-1020`, `TK-1027`, `TK-1035` |
| | `order_policy_and_refund_status`<br>（退改手續費規定與退款進度） | 維持不變（查取消手續費比例級距、查已退刷信用卡入帳天數） | `auto` | `TK-1038`, `TK-1048` |
| | `document_and_voucher_inquiry`<br>（訂單確認信、憑證與收據查詢） | **移出需人工改單的「發票統編重開/改三聯」**；僅保留確認信查詢、電子門票憑證催寄、英文收據開立詢問 | `auto`<br>*(註：72h 內急用由規則轉 `P4/human`)* | `TK-1001` (`auto`), `TK-1042` (`P4/human`), `TK-1046` (`auto`) |
| **3. `order_change`**<br>（訂單修改與資料更正） | `schedule_or_addon_change`<br>（改期、團體異動與加購申請） | 涵蓋已成立訂單申請改期、改接送飯店、部分團員退出、加購嬰兒票與托運行李 | `human` | `TK-1005`, `TK-1007`, `TK-1012`, `TK-1043`, `TK-1045` |
| | `data_or_invoice_correction`<br>（旅客資料與發票統編更正） | **新增/重組細項**：涵蓋**發票統編打錯重開（`TK-1010`）**、**二聯改開三聯發票（`TK-1039`）**、**護照英文名拼錯更正（`TK-1028`）** | `human` | **`TK-1010`**, `TK-1028`, **`TK-1039`** |
| **4. `order_refund`**<br>（訂單取消與退費申請） | `cancellation_refund_request`<br>（申請取消行程與退費） | 移出僅詢問颱風是否延期的 `TK-1021`；專注於**明確要求取消訂單並辦理退費**之案件 | `human` | `TK-1002`, `TK-1015` |
| | `refund_payout_request`<br>（退款匯款帳戶作業） | 維持不變（提供銀行帳號要求匯入退費款項） | `human` | `TK-1023` |
| **5. `complaint`**<br>（客訴與服務抱怨） | `service_or_channel_complaint`<br>（服務品質與通道抱怨） | 原 `pure_complaint` 更名，且**預設分流由 `auto` 改為 `human`**（客服電話等 40 分鐘沒人接、電話打不通皆由真人處理） | **`human`** | **`TK-1004`**, **`TK-1024`** |
| | `service_or_billing_dispute`<br>（實質服務瑕疵與扣款求償） | 維持不變（導遊失職、行程縮水、錯過班機、房間有蟑螂、重複扣款、客服報錯價求償） | `human` | `TK-1011`, `TK-1013`, `TK-1019`, `TK-1029`, `TK-1031`, `TK-1037`, `TK-1044` |
| **6. `system_and_account`**<br>（**新增大類**：系統與帳號問題） | `account_and_pricing_issue`<br>（會員帳號鎖定與網站計價異常） | **自 `order_info` 獨立為第 6 大類**：涵蓋會員帳號被鎖/收不到驗證碼（`TK-1016`）、官網標價與結帳系統跳價不符（`TK-1030`） | `human` | **`TK-1016`** (`P4/human`), **`TK-1030`** (`P2/human`) |
| **7. `other_non_cs`**<br>（非客服之業務與外部信件） | `business_pr_hr_referral`<br>（公司業務往來與跨部門轉介） | 原 `b2b_media_hr_referral` 更名並移出 `TK-1006`；專指供應商報價（`TK-1017`）、業配合作（`TK-1034`）、媒體採訪（`TK-1047`）、人資應徵（`TK-1026`） | `human` | **`TK-1017`**, `TK-1026`, `TK-1034`, `TK-1047` |
| | `spam_or_test`<br>（外部推銷廣告與系統測試單） | 維持不變（前置規則攔截） | `auto` | `TK-1008`, `TK-1041` |
| **8. `unknown`**<br>（待釐清／需補件） | `insufficient_info`<br>（資訊不足需補件） | 維持不變（前置規則攔截） | `auto` | `TK-1033` |

---

## 三、 受影響工單之新舊標註變更明細表

| 工單 ID | 主旨摘要 | 調整前 (`category / sub_category`, `priority`, `route`) | 調整後 (`category / sub_category`, `priority`, `route`) | 變更理由摘要 |
| --- | --- | --- | --- | --- |
| **`TK-1004`** | 打電話 40 分鐘沒人接！（問行程表） | `complaint / pure_complaint`<br>`P2`, `auto` | `complaint / service_or_channel_complaint`<br>`P2`, **`human`** | 客戶對服務態度強烈不滿且含行程表查詢，應由真人安撫與回覆 |
| **`TK-1024`** | 電話都打不通 | `complaint / pure_complaint`<br>`P2`, `auto` | `complaint / service_or_channel_complaint`<br>`P2`, **`human`** | 隨同 `complaint` 大類統一改為 `human` 真人處理 |
| **`TK-1006`** | 詢問企業包團服務（120人） | `other_non_cs / b2b_media_hr_referral`<br>`P1`, `human` | **`product_inquiry / customization_request`**<br>**`P2`**, `human` | 企業包團屬於高價值買方客製化旅遊詢價，屬客服/業務範圍（`P2`） |
| **`TK-1009`** | 郵輪艙房可否指定樓層 | `product_inquiry / customization_request`<br>`P2`, `human` | **`product_inquiry / product_spec_and_price`**<br>`P2`, **`auto`** | 屬於郵輪艙等選位規則之一般產品詢問，可由知識庫草擬回覆 |
| **`TK-1010`** | 發票統編打錯要重開 | `order_info / document_and_invoice`<br>`P2`, `auto` | **`order_change / data_or_invoice_correction`**<br>`P2`, **`human`** | 涉及已開立發票作廢與統編更正重開，需真人於系統修改處理 |
| **`TK-1039`** | 改開三聯式發票 | `order_info / document_and_invoice`<br>`P2`, `auto` | **`order_change / data_or_invoice_correction`**<br>`P2`, **`human`** | 與 `TK-1010` 相同，已開發票二聯改三聯需真人帳務作業處理 |
| **`TK-1014`** | 合掌村冬季會因大雪取消嗎 | `product_inquiry / product_spec_and_price`<br>`P2`, `auto` *(模型因信心 0.47 誤轉 human)* | **`product_inquiry / policy_and_regulation`**<br>`P2`, **`auto`** | 本質為天候停駛與退費通則詢問，歸入規則類後模型信心可大幅提升並穩定走 `auto` |
| **`TK-1021`** | 明天出發，颱風會不會延期？？ | `order_refund / cancellation_refund_request`<br>`P4`, `human` | **`product_inquiry / policy_and_regulation`**<br>`P4`, `human` | 客戶是在詢問颱風是否延期與退費規則（尚未申請取消），因明日出發急件規則升為 `P4 / human` |
| **`TK-1016`** | 會員帳號被鎖無法登入 | `order_info / account_and_pricing_issue`<br>`P4`, `human` | **`system_and_account / account_and_pricing_issue`**<br>`P4`, `human` | 獨立出 `system_and_account` 系統與帳號大類，不再寄生於 `order_info` |
| **`TK-1030`** | 網頁價格與結帳金額不同 | `order_info / account_and_pricing_issue`<br>`P2`, `human` | **`system_and_account / account_and_pricing_issue`**<br>`P2`, `human` | 屬於網站系統結帳金額異常（非既有訂單查詢），歸入 `system_and_account` |
| **`TK-1017`** | Re: 7月包車報價單 | `other_non_cs / b2b_media_hr_referral`<br>`P1`, `human` | `other_non_cs /` **`business_pr_hr_referral`**<br>`P1`, `human` | 細項正名為「公司業務往來與跨部門轉介」，與 B2B 企業客戶買團區隔 |

---

## 四、 待確認事項（確認後即可同步修改規格文件與 PoC）

請確認以上調整方向是否符合您的預期，特別是以下 3 個細節：
1. **`TK-1039`（二聯式發票改開三聯式）**：是否同意與 `TK-1010`（發票統編打錯重開）一併歸入 `order_change / data_or_invoice_correction`（`route = human`）？
2. **`TK-1024`（電話都打不通）**：將 `complaint / service_or_channel_complaint` 預設改為 `route = human` 後，`TK-1004` 與 `TK-1024` 都會走 `human`（即所有客訴抱怨一律由真人處理），這樣是否符合您的想法？
3. **`system_and_account`（系統與帳號問題）的細項顆粒度**：目前樣本中僅 `TK-1016`（帳號被鎖）與 `TK-1030`（網頁與結帳價差）2 筆，合併為單一細項 `system_and_account / account_and_pricing_issue` 可以讓 Stage 1 模型總選項維持在 **14 個**（最利於小模型維持高信心分數），還是您希望拆成 `account_login_issue` 與 `website_pricing_issue` 兩個細項（共 15 個選項）？
