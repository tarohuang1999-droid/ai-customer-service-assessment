# Implement Plan：分類機制重構與文件一致性修正

對應 `review-claude.md`。目標：

1. 移除「看答案」式的分類描述與規則，讓 PoC 的結果經得起追問。
2. 重新設計分類與 route：細項單一概念、邊界清楚。
3. answer、taxonomy spec、PoC 三者一致。
4. 精簡程式碼，但保留 `review.html`。

**範圍原則**
- 不另做合成資料，只用 48 筆樣本（小專案不過度工程）。
- **工單 ID 規則**：answer 相關文件（`answer-v0-gemini.md`、`taxonomy-and-priority-spec.md`）不出現工單 ID，也不出現樣本特有情節，避免讓人以為是看答案寫的。PoC 的 `review.html`、`triage_result.csv`、`expected_labels.csv`、README 的資料發現可以有 ID。
- **PoC 不能看答案**：`labels.toml` 描述、mock 關鍵字、regex 規則都只能寫通用定義，不能寫入樣本句子、金額、地名或人數。

| Phase | 內容 | 主要檔案 | 預估 |
|---|---|---|---|
| 1 | 定案 taxonomy v2，重寫 spec | `taxonomy-and-priority-spec.md` | 1h |
| 2 | PoC 分類與 route 機制 | `config/*.toml`、`pipeline/*.py` | 2h |
| 3 | 依新標準重新標註 `expected_labels.csv` | `poc/data/expected_labels.csv` | 0.5h |
| 4 | 精簡 `evaluate.py`，保留 `review.html` | `evaluate.py`、`triage.py` | 1h |
| 5 | README 更新 | `poc/README.md` | 0.5h |
| 6 | answer 同步 | `answer-v0-gemini.md` | 1h |
| 7 | `.gitignore` 與一致性檢查 | `.gitignore` | 0.5h |
| 8 | 交付包 | `submission/`、`submission.zip` | 0.5h |

---

## Phase 1：taxonomy v2

### 1.1 兩條分類原則

1. **細項只代表一個概念**：命名不用 and／or；需要用 and 描述的，就拆成兩個細項。
2. **route 由「完成工單需要的動作」決定**：

| 需要的動作 | 預設 route |
|---|---|
| 不需訂單資料，查知識庫即可回答 | `auto`（草擬） |
| 需要唯讀查詢訂單或會員資料 | `auto`（草擬） |
| 需要在既有系統寫入（改單、退款、發票更正） | `human` |
| 需要調查或判斷責任（系統異常、旅途異常、客訴） | `human` |
| 非客服：需轉交其他部門 | `human`（轉交） |
| 非客服：無關信件 | `auto`（歸檔，不生成） |
| 資訊不足 | `auto`（固定補件模板） |

`auto` 一律代表「產出草稿，經客服確認後送出」，B 階段不直接寄信。

### 1.2 類別表（8 大類、18 個細項，全部由模型選；單題選項數 < 20）

| 大類 | 細項 | 定義（通用） | 不含 | route | 預設 priority |
|---|---|---|---|---|---|
| `product` 產品與規定詢問 | `product_info` | 行程內容、費用包含項目、計價方式、加購項目的價格與期限、票券兌換與使用、艙房或座位規則 | 要求客服代為修改已成立訂單 | auto | P2 |
| | `travel_rule` | 證照、簽證、入境規定、天候或不可抗力時的出團與退費通則 | 旅途中正在發生的異常 | auto | P2 |
| | `cancel_policy` | 取消或改期的手續費規定、定型化契約級距 | 實際申請取消 | auto | P2 |
| | `custom_request` | 需要另外評估或向供應商確認的需求：團體包團報價、無障礙、特殊飲食 | 標準規則即可回答 | human | P2 |
| `order_inquiry` 訂單查詢 | `order_status` | 訂單是否成立、行前通知或行程表寄送時間 | 要求修改訂單 | auto | P2 |
| | `refund_status` | 已申請退款的進度與入帳時間 | 申請退款 | auto | P2 |
| | `document` | 補寄確認信或電子憑證、開立新收據 | 已開立單據的更正 | auto | P2 |
| | `member_points` | 會員點數餘額、折抵與到期規則 | — | auto | P2 |
| `order_change` 訂單異動 | `booking_change` | 已成立訂單的變更與費用調整：改期、改人數、改接送地點、代為加購、取消、退費、提供退款帳戶 | 只詢問規定或價格 | human | P2 |
| | `data_correction` | 旅客資料或已開立發票的更正 | 新開收據 | human | P2 |
| `system_issue` 系統異常 | `account_access` | 無法登入、帳號鎖定、收不到驗證碼 | — | human | P2 |
| | `checkout_error` | 付款失敗、重複扣款、結帳金額與標價不符 | 退款進度查詢 | human | P2 |
| `trip_incident` 旅途異常 | `disruption` | 已出發後需要即時協助：住宿問題、人員未到、證件遺失、受傷、滯留 | 出發前的天候詢問（歸 `travel_rule`）；事後求償（歸客訴） | human | P4 |
| `complaint` 客訴 | `service_complaint` | 對服務品質或聯絡管道的抱怨，沒有具體求償 | — | human | P2 |
| | `compensation_claim` | 要求賠償、退還費用，或揚言申訴 | — | human | P3 |
| `other` 非客服 | `business` | 需要轉交其他部門的對外往來：供應商、合作提案、媒體、求職 | 客戶的團體詢價（歸 `custom_request`） | human | P1 |
| | `irrelevant` | 廣告、測試單、自動回覆等無關信件 | — | auto | P1 |
| `unclear` 待補件 | `insufficient_info` | 看不出訴求，或缺少處理所需的訂單資訊 | — | auto | P2 |

**相較現行版本的主要變動**

- 抱怨全部改為 `human`。
- 團體包團詢價移到 `product/custom_request`，優先級為 P2。
- 已開立發票的更正改為 `order_change/data_correction`，route 為 `human`。
- 帳號問題與結帳異常獨立成 `system_issue`。
- 新增 `trip_incident`，用來和事後客訴區分。
- 「詢問」和「申請執行」拆開：詢問規定或價格歸 `product`／`order_inquiry`（auto）；要求客服對已成立訂單做變更歸 `order_change/booking_change`（human）。
- 改期、改人數、取消、退費常伴隨費用調整，合併為單一細項 `booking_change`。
- `product` 和 `order_inquiry` 的界線是「需不需要訂單資料」。
- 移除 `too_short` 規則類別；資訊不足由模型選 `unclear/insufficient_info`。

### 1.3 優先級（維持 P1 低 → P4 最高）：分類 × 急迫度 × 影響程度

模型每筆回答 3 題：分類、急迫度（`urgency`）、影響程度（`impact`）。優先級依下列順序決定：

1. **急迫度 × 影響程度對應表**（模型信心 < 0.70 的程度視為 `low`）

| 急迫度 \ 影響程度 | high | medium | low |
|---|---|---|---|
| **high** | P4 | P4 | P4 |
| **medium** | P3 | P2 | P2 |
| **low** | P3 | P2 | P2 |

2. **分類下限**：取「對應表結果」與「細項預設 priority」的較高者，例如 `trip_incident` 至少 P4，`compensation_claim` 至少 P3。
3. **規則調升**：

| 規則 | 至少調升到 |
|---|---|
| 72 小時內出發或使用 | P4 |
| 金額 > 30,000 且有金錢語境 | P3 |
| 升級字眼（消保官、律師、提告、媒體、爆料、公開、銀行爭議款、止付；排除採訪邀約語境） | P3 |
| 重複催單 | P3 |

4. `other` 大類固定為 P1，不受上述調升。

**程度定義（通用）**

| 維度 | high | medium | low |
|---|---|---|---|
| 急迫度 | 72 小時內出發或使用、旅途中、當日必須處理 | 兩週內出發或使用，或有明確截止期限（付款、報帳） | 其他 |
| 影響程度 | 金額 > 30,000、重複扣款、求償、揚言申訴、人身安全、交易無法完成（如待付款卻無法登入或付款） | 需要修改訂單或調整費用 | 資訊詢問、非客服信件 |

### 1.4 spec 文件修改

- 開頭寫明：「本文件為類別、route、priority 的唯一定義來源；`labels.toml` 與 answer Q2 皆以此為準。P4 為最高。」
- 章節：route 原則 → 類別表 → priority → 硬性轉人工規則 → 複合意圖（以風險最高的訴求決定，由模型選出的細項承擔）→ 已知未涵蓋（表揚、個資刪除請求，由低信心轉人工承接）。
- 不出現工單 ID 與樣本情節。

---

## Phase 2：PoC 分類與 route

### 2.1 `config/labels.toml`

- 依 1.2 重寫 18 個選項，描述只寫「定義」和「不含」，不寫任何樣本內容。
- 每個選項保留 `route` 與 `priority` 欄位。
- 移除 `precheck_only` 選項。

### 2.2 模型呼叫：維持每筆 3 次

- `classification`（18 選 1）、`urgency_level`、`impact_level` 各一次。
- 3 題的選項描述都依 1.2 與 1.3 改寫為通用定義，不含樣本內容。

### 2.3 `router.py`：4 步驟

1. **規則歸檔**：廣告或測試單 → `other/irrelevant`，不呼叫模型。
2. **模型 3 題**：取得細項與分類信心，查表得到預設 route；依 1.3 計算 priority。
3. **硬性規則**：命中 1.3 任一規則 → route 改為 `human`，priority 調升；`human` 不會被改回 `auto`。
4. **信心門檻**：分類信心 < 0.70 → `human`。

模型失敗或逾時 → `human`、P3（fail-closed）。

**`reason` 格式**：分類信心，有命中規則時再附上規則名稱。

- `分類信心 0.91`
- `分類信心 0.88；轉人工：72 小時內出發`
- `分類信心 0.55；轉人工：信心不足`

### 2.4 `regex_rules.toml` 與 `signals.py`

- **刪除**：
  - 針對個別樣本的特例字眼
  - 短信判斷中排除特定字詞的寫法
  - `too_short` 規則
  - 外部法規變動 regex（改由草擬階段的知識庫檢索判斷有無依據）
- **72 小時**：解析內文日期（沒有年份時取最近的未來日期）與相對日期（今天、今晚、明天、明日、後天），與 `created_at` 比較；需同時出現出發、使用、入住、搭乘、進場等語境。
- **金額**：支援逗號、「萬」與中文數字；排除萬粉、萬人等非金額用法。
- **升級字眼與重複催單**：使用 1.3 的通用清單。重複催單由通用字眼（再次、還沒回、到底、催）加上同名比對判斷。
- **`has_inline_pii`**：只標記，不影響 route，作為外部遮罩系統的觸發訊號。

### 2.5 `preprocess.py`

- `<br>`、`<p>` 轉為換行，移除其他標籤，HTML entity 解碼。
- 移除手機簽名（如「從我的 iPhone 傳送」、「Sent from my」）、`>` 開頭的引用行，以及原始郵件分隔線之後的內容。
- 記錄每種清理的件數，供 `review.html` 的資料發現區塊使用。

### 2.6 `models.py`

- `MockDecisionModel` 改用依 spec 定義建立的通用詞庫，不含樣本句子；README 註明 mock 只用來確認流程可以執行。
- `JevAPIClient` 保留，CLI 說明標示「遠端模式僅限虛構資料，真實工單須經法務核准」。

**完成條件**：在 `config/` 與 `pipeline/` 中搜尋樣本特有的金額、地名、人名、商品名，結果為 0。

---

## Phase 3：依新標準重新標註 `expected_labels.csv`

- 依 1.2 與 1.3 標註，草稿見**附錄 A**。
- 欄位：`ticket_id, category, sub_category, priority, route`。
- 作者確認附錄 A 後才寫入 CSV，之後不再為了提高分數修改。
- README 誠實說明：48 筆是開發時看過的資料，準確率只代表開發集；正式驗收要用 Q2 提到的 50–100 筆真實歷史工單。

---

## Phase 4：精簡 `evaluate.py`，保留 `review.html`

- **保留**：`review.html`（含工單 ID）、`triage_result.csv`、`run.log`、每次執行的目錄、`--serve`。
- **`review.html` 內容**：
  - 執行摘要：類別分佈、需人工比例、priority 分佈
  - 資料發現（題目要求）
  - 評估：大類、細項、route 準確率；False Auto 件數；信心 ≥ 0.70 與 < 0.70 各自的準確率
  - 逐筆表格：工單 ID、預測、標準答案、`reason`、是否一致，可篩選
- **精簡**：
  - 逐階段計時改為只在 `run.log` 記錄，HTML 只顯示每筆總耗時與平均值。
  - HTML 模板與計算邏輯分開，目標從 503 行降到約 250 行。

---

## Phase 5：README（`poc/README.md`）

1. 執行方式：mock（乾淨環境）、llamacpp（地端）、jev（遠端，僅限虛構資料）
2. **決策模型說明**（新增）：
   - Jev／Kev／Clef 是決策模型：給定狀態與選項，一次計算就輸出各選項機率，不生成文字。
   - 相較讓 LLM 直接分類：更快、更省，沒有格式解析錯誤或幻覺類別，信心度可以直接設門檻。
   - Clef 以 GGUF 搭配 llama.cpp 地端部署，工單不出內網。
   - 信心度是否可靠，以 `review.html` 的信心分箱結果檢驗。
3. 分類與 route 原則（摘要，連到 spec）
4. Router 4 步驟與 `reason` 格式
5. 資料發現與處置（可列工單 ID）：尾端空欄、全形字、HTML 標籤與簽名檔、廣告與測試單、同名重複來信、內文個資、英文信件、非客戶寄件者、沒有年份的日期、非金額的「萬」
6. 評估：開發集定位與限制
7. 設計取捨：不生成草稿、不做個資遮罩（外部系統）、不做簽核（既有系統）、不合併工單、不做合成資料
8. 已知限制
9. 進正式環境最重要的三件事

---

## Phase 6：answer 同步（`answer-v0-gemini.md`）

| 位置 | 修改 |
|---|---|
| Q2 §2 非目標 | 「不接管去重、歸戶」改為：「不合併工單；只讀取工單系統的未結案件狀態，作為分流訊號」 |
| Q2 §3 類別表 | 換成 8 大類與 route 原則，細項連到 spec |
| Q3 §1 | 補一句決策模型說明；保留「分 3 次 Choice」，並補上「優先級 = 急迫度 × 影響程度對應表，再套用分類下限與規則調升」 |
| Q3 §2 流程圖 | 生成節點前後加上外部系統：「個資遮罩 → LLM 生成 → 還原 → 客服審核」 |
| Q3 §3 分工表 | AI 欄：分類、急迫度、影響程度；規則欄：對應表、分類下限、規則調升與 route 覆寫 |
| Q3 §4 觸發條件 | 與 spec 和 `route_rules.toml` 逐條對應；外部法規改為「檢索無依據」；範例改為通用情境 |
| Q3 §6 | 寫明遮罩與還原由外部系統負責；決策模型地端部署時，分流階段不需遮罩 |
| 全文 | 刪除工單 ID 與樣本特有情節 |
| Q4（次要） | 任務成功率改為 auto、human 分開計算；人工接手率拆成「設計內轉人工」與「auto 被推翻」 |
| Q5（次要） | 「回覆時間改善主要來自分流」改寫成待以 log 驗證的假設 |
| AI 使用說明 | 寫出具體環節與工具 |

依作者決定：Q1、Q2 不引用 PoC 數字；優先級方向不改。

---

## Phase 7：`.gitignore` 與一致性檢查

### 7.1 `.gitignore`（專案根目錄，只排除產生物）

```
.DS_Store
**/__pycache__/
*.pyc
.venv/
poc/output/run/
submission/
*.zip
```

草稿與 review 檔留在 repo 方便追蹤，不放進交付包（見 Phase 8）。

### 7.2 檢查清單

- [ ] spec、`labels.toml`、answer Q2 的類別與 route 一致
- [ ] spec、`route_rules.toml`、answer Q3 §4 的硬性規則與優先級對應表一致
- [ ] answer 與 spec 搜尋 `TK-`，結果為 0
- [ ] `config/`、`pipeline/` 不含樣本特有字串
- [ ] 乾淨環境執行 `uv run python triage.py --model mock`，產出 48 筆結果與 `review.html`

---

## Phase 8：交付包（最後一步）

建立 `submission/` 與 `submission.zip`，只放題目要求的內容：

```
submission/
├── answers.md                       # 由 answer-v0-gemini.md 改名，連結改為相對路徑
├── taxonomy-and-priority-spec.md
└── poc/
    ├── README.md
    ├── pyproject.toml
    ├── uv.lock
    ├── triage.py
    ├── evaluate.py
    ├── pipeline/
    ├── config/
    ├── data/                         # sample_tickets.csv、expected_labels.csv
    └── output/                       # 最新一次的 triage_result.csv、review.html、run.log
```

不放：草稿與 review 檔、`archieve/`、`docs/note.md`、`output/run/` 歷史、`.git`。打包後在乾淨目錄解壓、照 README 執行一次。

---

## 附錄 A：`expected_labels.csv` 標註草稿（依 taxonomy v2）

route 與 priority 已套用 1.3 的對應表與規則；「依據」欄說明非預設值的原因。

| ticket_id | category | sub_category | priority | route | 依據 |
|---|---|---|---|---|---|
| TK-1001 | order_inquiry | order_status | P2 | auto | 確認訂單是否成立 |
| TK-1002 | order_change | booking_change | P2 | human | 申請取消 |
| TK-1003 | product | product_info | P2 | auto | |
| TK-1004 | complaint | service_complaint | P2 | human | 抱怨加查詢，以風險較高者為準 |
| TK-1005 | order_change | booking_change | P2 | human | 加購 |
| TK-1006 | product | custom_request | P2 | human | 團體包團報價 |
| TK-1007 | order_change | booking_change | P2 | human | 改期 |
| TK-1008 | other | irrelevant | P1 | auto | 廣告 |
| TK-1009 | product | product_info | P2 | auto | 艙房規則 |
| TK-1010 | order_change | data_correction | P2 | human | 發票更正 |
| TK-1011 | complaint | compensation_claim | P3 | human | 要求退費並揚言公開 |
| TK-1012 | order_change | booking_change | P2 | human | 改接送地點 |
| TK-1013 | system_issue | checkout_error | P3 | human | 重複扣款，金額 > 3 萬，銀行爭議款 |
| TK-1014 | product | travel_rule | P2 | auto | 天候出團通則 |
| TK-1015 | order_change | booking_change | P3 | human | 申請取消退費，金額 > 3 萬 |
| TK-1016 | system_issue | account_access | P3 | human | 影響程度 high：待付款訂單無法完成 |
| TK-1017 | other | business | P1 | human | 供應商 |
| TK-1018 | product | travel_rule | P2 | auto | |
| TK-1019 | complaint | compensation_claim | P3 | human | 揚言消保官、媒體；重複反映 |
| TK-1020 | order_inquiry | order_status | P2 | auto | |
| TK-1021 | product | travel_rule | P4 | human | 天候詢問；72 小時內出發 |
| TK-1022 | product | custom_request | P2 | human | 特殊飲食 |
| TK-1023 | order_change | booking_change | P2 | human | 提供退款帳戶（含個資） |
| TK-1024 | complaint | service_complaint | P2 | human | |
| TK-1025 | product | product_info | P2 | auto | |
| TK-1026 | other | business | P1 | human | 求職 |
| TK-1027 | order_inquiry | member_points | P2 | auto | |
| TK-1028 | order_change | data_correction | P2 | human | 旅客資料更正 |
| TK-1029 | complaint | compensation_claim | P3 | human | 求償 > 3 萬 |
| TK-1030 | system_issue | checkout_error | P2 | human | 標價與結帳不符 |
| TK-1031 | system_issue | checkout_error | P3 | human | 重複催單、止付 |
| TK-1032 | product | custom_request | P2 | human | 無障礙 |
| TK-1033 | unclear | insufficient_info | P2 | auto | 補件模板 |
| TK-1034 | other | business | P1 | human | 合作提案 |
| TK-1035 | order_inquiry | order_status | P2 | auto | |
| TK-1036 | product | product_info | P2 | auto | |
| TK-1037 | trip_incident | disruption | P4 | human | 旅途中住宿問題 |
| TK-1038 | order_inquiry | refund_status | P2 | auto | |
| TK-1039 | order_change | data_correction | P2 | human | 發票改開 |
| TK-1040 | product | travel_rule | P2 | auto | 法規時效改由草擬階段檢索判斷 |
| TK-1041 | other | irrelevant | P1 | auto | 測試單 |
| TK-1042 | order_inquiry | document | P4 | human | 72 小時內使用 |
| TK-1043 | order_change | booking_change | P2 | human | 改人數與費用調整 |
| TK-1044 | complaint | compensation_claim | P3 | human | 要求退還多收款 |
| TK-1045 | product | product_info | P2 | auto | 只詢問加購價格與期限，未要求代為修改 |
| TK-1046 | order_inquiry | document | P2 | auto | 開立新收據 |
| TK-1047 | other | business | P1 | human | 媒體 |
| TK-1048 | product | cancel_policy | P2 | auto | 手續費級距 |

合計：auto 18 筆、human 30 筆。

## 附錄 B：已確認的決策

1. 模型維持每筆 3 次呼叫：分類、急迫度、影響程度；優先級以對應表綜合決定。
2. 帳號鎖定且有待付款訂單 → P3（由影響程度「交易無法完成」得出，不為個別工單寫規則）。
3. 改期、改人數、取消、退費合併為 `booking_change`。
4. 加購：只詢問價格或期限 → `product/product_info`（auto）；要求客服修改已成立訂單 → `order_change/booking_change`（human）。
