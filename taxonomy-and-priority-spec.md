# 附件：工單分類細項（Sub-category）與優先級（Priority）初始定義

本文件補充 [answer-v0-gemini.md](answer-v0-gemini.md) Q2「輸入／輸出定義」的細項，供開工前與客服主管對齊。PoC 的 48 筆樣本標註獨立存放於 [poc/data/expected_labels.csv](poc/data/expected_labels.csv)。

---

## 1. 優先級（Priority）初始定義（`P1` 低優先 -> `P4` 超重要，由 `urgent_level` × `impact_level` 決定）

最終門檻於開工前與客服主管確認。

| 優先級 | 判定基準（`urgent_level` / `impact_level` / 規則） | 典型情境 | 佇列處置與預設 `route` |
| --- | --- | --- | --- |
| `P4` 超重要（極緊急） | `urgent_level = high` 或規則命中 72 小時內出發／使用異常、旅途中安全或食宿異常、帳號安全問題 | 旅途中飯店環境異常、明日出發遇颱風停航、明日使用卻未收到電子憑證、帳號被鎖且有待付款訂單 | 置頂最優先處理；`human` |
| `P3` 高（高影響） | `impact_level = high` 或規則命中退改／求償 > 30,000 元、帳務扣款爭議、重複催單、投訴語境中揚言找消保官或媒體 | 高額行程因傷病申請全額退費、領隊失職求償、疑似重複扣款與二次催單、揚言向消保官或媒體申訴 | 優先排入人工佇列；`human` |
| `P2` 一般（標準） | `urgent_level = low/medium` 且 `impact_level = low/medium`：一般產品詢問、訂單與退改規定查詢、單據補發、常規修改與取消申請、純抱怨、缺資料待補件 | 詢問團費包含項目、取消手續費級距規定、退款入帳天數、未收到確認信、申請改期或取消、純抱怨電話打不通、內文過短無法判斷意圖 | 依進件時間排序；產品與訂單規定查詢走 `auto`，實際申請改單與退費走 `human` |
| `P1` 低 | 非客服業務轉介、外部雜訊（`other_non_cs`） | 企業包團詢價、供應商報價、媒體採訪邀約、職缺應徵、推銷廣告與系統測試單 | 排在佇列末端；廣告與測試單由規則標記 `auto`，其餘 `human` 轉交對應部門 |

---

## 2. 主類別與細項分類對照表（7 大類）

- **複合意圖**：以風險最高的訴求決定主類別、`priority` 與 `route`，其餘訴求保留為輔助標籤。
- **語意與權責分離原則**：
  - 凡屬於**「查詢訂單狀態、詢問取消手續費規定、詢問退款入帳進度或索取單據」**，歸入 `order_info`，由 AI 依客戶行程查知識庫與唯讀 API 草擬回覆（預設 `auto`）。
  - 凡屬於**「實際要求變更／加購既有訂單」**歸入 `order_change`，**「實際要求取消訂單／辦理退費」**歸入 `order_refund`，預設一律為 `human`，由真人在既有系統處理。

| 主類別 (`category`) | 細項 (`sub_category`) | 涵蓋情境 | 預設 `route` | B 階段系統處置 |
| --- | --- | --- | :---: | --- |
| `product_inquiry`<br>（售前產品詢問） | `product_spec_and_price` | 行程內容、費用包含項目、兒童收費、票券兌換、購買前詢問天氣停駛通則 | `auto` | 檢索知識庫，生成附來源的草稿 |
| | `policy_and_regulation` | 護照效期、簽證、保險與旅遊通則 | `auto` | 檢索通則生成草稿；外部最新法規無明確依據時轉 `human` |
| | `customization_request` | 無障礙評估、特殊飲食、指定郵輪艙房或客製化安排 | `human` | AI 摘要；客服向供應商確認 |
| `order_info`<br>（訂單與規定查詢） | `order_status_and_points` | 訂單狀態、行前通知與行程表寄送時程、點數折抵規則 | `auto` | 結合知識庫與訂單唯讀資料生成草稿 |
| | `order_policy_and_refund_status` | 詢問出發前取消手續費比例規定、已辦理之信用卡退款入帳工作天數（未要求執行退改） | `auto` | 檢索退改定型化契約條文與退款進度生成說明草稿 |
| | `document_and_invoice` | 確認信或憑證補發、發票統編修改、開立收據（72 小時內急用除外） | `auto` | 生成標準補發或發票處理草稿 |
| | `account_and_pricing_issue` | 帳號鎖定無法登入、網頁價格與結帳金額不符 | `human` | AI 摘要；客服在既有系統查證 |
| `order_change`<br>（訂單修改與加購） | `schedule_or_group_change` | 實際申請改期並問差價、更換接送飯店、團體部分人員退出 | `human` | AI 摘要與相關條文；客服在既有系統核算差價與改單 |
| | `passenger_or_addon_change` | 更正旅客護照英文拼音、已訂訂單申請加購嬰兒票或托運行李 | `human` | AI 摘要與相關條文；客服在既有系統變更與加購 |
| `order_refund`<br>（訂單取消與退費） | `cancellation_refund_request` | 因傷病住院、骨折、天災颱風實際申請取消行程與退費 | `human` | AI 摘要與退費條文；客服在既有系統核算與辦理退費 |
| | `refund_payout_request` | 已取消訂單提供銀行帳號要求匯入退費款項 | `human` | AI 摘要；客服在既有系統核對帳務辦理匯款 |
| `complaint`<br>（客訴與爭議） | `pure_complaint` | 純抱怨（如電話打不通、等太久），未提出補償或具體處理要求 | `auto` | 生成致歉草稿；若同時有常規詢問，一併解答 |
| | `service_or_billing_dispute` | 旅途中食宿異常、領隊失職、重複扣款、報錯價、要求補償或退款、揚言申訴 | `human` | 調升為 P3／P4；AI 摘要後由真人處理 |
| `other_non_cs`<br>（非客服信件） | `b2b_media_hr_referral` | 企業包團、供應商報價、媒體邀約、業配、應徵 | `human` | 標記對應部門，客服轉交 |
| | `spam_or_test` | 外部推銷、博弈廣告、系統測試單 | `auto` | 規則標記 spam，不生成回覆，客服一鍵關閉 |
| `unknown`<br>（待釐清／需補件） | `insufficient_info` | 內文過短無法判斷意圖、缺訂單號等必要資料 | `auto` | 不呼叫 AI；套用固定補件模板，客服確認後送出（階段三優先開放自動回信） |
