# Implement Plan — Phase 2

**這份文件說明接下來要做什麼。**`implement-plan.md` 是過去幾輪的紀錄，執行時以本文件為準。

---

## 1. 目標

1. **False Auto = 0**：應由人處理的工單，絕不能進 auto。
2. 標準答案、spec、answer、README、PoC 五處對 route 的定義一致。
3. PoC 流程簡單、可以說清楚：前處理 → 決策模型 3 題 → 對應表 → 輸出。

## 2. 現況

最近一次 Clef 實跑（`output/result-20261030_225155`）：

| 指標 | 結果 | 問題 |
| --- | --- | --- |
| 主類別／細項 | 95.8% | 沒問題。分類信心 ≥ 0.70 的 40 筆全部正確 |
| route | 85.4% | **2 筆 False Auto**：細項是 auto，急迫度判成 high，但 route 不看程度<br>5 筆 False Human：分類正確，但信心 < 0.70 |
| priority | 75.0% | 拿掉了程度的信心門檻，11 筆低信心的急迫度 high 被採用，判成 P4 |
| 平均分類信心 | 0.80（上一版 0.84） | 改寫描述與加入進件時間同時上線，原因待分離 |

用同一份 Clef 輸出試算第 4 節的流程（T = 0.6）：route 45/48、**False Auto 0**。

## 3. 原則（作者已確定）

1. False Auto 絕對禁止；寧可多轉人工。
2. 先審視標準答案，再改流程。
3. **route 的定義**：auto = AI 能決定回覆的絕大部分內容，且不急迫；其餘為 human。
4. 進件時間不放進模型輸入，並在 README 說明原因。
5. 流程圖只畫主要階段，採用作者版本。
6. 前處理只做必要的事，README 不寫沒做的處理。
7. README 要說明 pipeline 各模組的職責與分類邏輯，並與 answer、spec 對齊。

---

## 4. 決策

### 4.1 流程（作者已決定）

| # | 作者決定 | 落實方式 |
| --- | --- | --- |
| D1 | 分類信心不足 → `other/unclear` | 新增細項 `other/unclear`（待人工判斷），route = human。**優先級依程度決定，不套用 `other` 固定 P1**，避免取消、退費這類工單沉到佇列最後 |
| D2 | 急迫度 high、影響程度 high 與 route 分類一起決定 route | 細項對應表先決定預設 route；急迫度或影響程度為 high 時，透過 D3 的風險分數轉 human |
| D3 | 三個信心分別乘上權重，加總超過閾值就轉人工 | 見下方「風險分數」 |
| D4 | 信心門檻可以微調；False Auto 必須為 0，其他指標越高越好 | 閾值選擇規則見 4.3 |
| D5 | 不要 overfitting | 見 4.3 |

**風險分數**

```
risk = w_c × (1 − 分類信心) + w_u × u + w_i × i

u = 急迫度選 high 時的信心，否則為 0
i = 影響程度選 high 時的信心，否則為 0
```

**完整流程**

1. 決策模型回答 3 題：細項分類、急迫度、影響程度。
2. 分類信心 < θ_c → 細項設為 `other/unclear`，route = human。
3. 否則依細項對應表得到預設 route。
4. `risk ≥ T` → route = human。只會把 auto 改成 human，不會反過來。
5. priority：急迫度 × 影響程度對應表（程度信心 < 0.70 視為 low）→ 套用細項下限 → `other/business`、`other/irrelevant` 固定 P1（`other/unclear` 除外）。
6. 模型逾時或錯誤：route = human、P3，`run.log` 記錄發生在哪一題、錯誤類型、重試次數。

`reason` 寫分類信心與風險分數，例如 `分類信心 0.76；風險 1.01 ≥ 0.60，轉人工`。

### 4.3 初始參數與防止 overfitting

**用上次 Clef 輸出試算**（w_c = w_u = w_i = 1；只看 D2、D3，尚未加入 D1）

| 閾值 T | route | False Auto | False Human |
| --- | --- | --- | --- |
| 0.4 | 43/48 | 0 | 5 |
| 0.5 | 45/48 | 0 | 3 |
| 0.6 | 45/48 | 0 | 3 |
| 0.7 | 46/48 | 0 | 2 |
| 0.8 | 48/48 | 0 | 0 |

細項為 auto 的工單中，兩筆必須轉人工的急件風險分數是 1.01 和 1.29；應該維持 auto 的工單，最高分數是 0.78。T = 0.8 剛好卡在兩群之間，所以 48/48 全對。**這正是 overfitting**：換一批資料，急件的分數只要低一點，就會變成 False Auto。

**防止 overfitting 的做法**

1. **權重不搜尋**：w_c = w_u = w_i = 1，依「三個訊號同等重要」的原則設定，不用 48 筆去找最佳權重。若之後要調整，必須有業務上的理由（例如「急迫度比影響程度更重要」），不能只因為分數變高。
2. **閾值留安全距離**：選擇 T 時，必須轉人工的工單中風險最低的那一筆，至少要比 T 高 0.3。依此規則，初始值為 **T = 0.6**（1.01 − 0.6 = 0.41），接受 3 筆 False Human。
3. **θ_c 初始值 0.5**：分類信心低於 0.5 才歸到 `other/unclear`；0.5–0.7 之間由風險分數處理。實跑後再看 `other/unclear` 的件數是否合理。
4. **調參過程公開**：README 列出 T 的試算表與選擇理由，面試時能說明為什麼不選 0.8。
5. **描述與標註不為個別工單調整**：`labels.toml` 只寫通用定義；`expected_labels.csv` 的修改必須能用 spec 的定義解釋（見 4.2）。
6. **評估時把 `other/unclear` 分開計算**：歸到 `other/unclear` 代表系統承認判斷不了，報表另外列出「判斷不了的比例」與「有判斷時的準確率」，不直接算成分類錯誤。

**需要作者確認的一點**：現有的 `unclear/insufficient_info`（模型判斷「客戶資訊不足」，套用補件模板、auto）和新的 `other/unclear`（系統信心不足、轉人工）名稱相近，但意義和 route 都不同。建議兩者都保留；若覺得容易混淆，可以把前者改名為 `unclear/need_more_info`。

### 4.4 標準答案：13 筆有疑問（**尚待作者確認**）

依原則 3 重新檢查 48 筆。其餘 35 筆沒有爭議。作者回覆「照建議」即採用建議欄；#7 需要作者選 P2 或 P3。

| # | 工單 | 目前標註 | 疑問 | 建議 |
| --- | --- | --- | --- | --- |
| 1 | TK-1004 電話 40 分鐘沒人接（順帶問行程表） | complaint/service_complaint · human · P2 | 回覆內容 AI 寫得出來，依原則 3 可能是 auto | **維持 human**：要不要補償、怎麼安撫是人的判斷，AI 決定不了 |
| 2 | TK-1024 電話都打不通（一句話） | complaint/service_complaint · human · P2 | 同上；內容很短，也可能歸 unclear | **維持**：有明確不滿，不是資訊不足 |
| 3 | TK-1009 郵輪艙房可否指定樓層 | product/product_info · auto · P2 | Clef 兩次信心都低，與 custom_request 混淆 | **維持 auto**：知識庫可以回答指定規則 |
| 4 | TK-1045 加購行李的價格與期限 | product/product_info · auto · P2 | 客戶似乎已有訂單，價格要查該筆訂單 | **改為 order_inquiry**（需要訂單資料），route 仍為 auto；需新增或擴充對應細項 |
| 5 | TK-1040 泰國簽證最近有變 | product/travel_rule · auto · P2 | 知識庫可能過期 | **維持 auto**：分流階段無法得知知識庫新不新，由草擬階段「查無有效依據 → human」處理 |
| 6 | TK-1030 網頁標價與結帳金額不同 | system_issue/checkout_error · human · P2 | 可能只是正常加價 | **維持 human**：是不是系統錯誤要查了才知道 |
| 7 | TK-1016 帳號被鎖，有待付款訂單 | system_issue/account_access · human · P2 | 作者先前說過 P3，後來又說影響不大 | **請作者決定**。若選 P3，影響程度 high 要加上通用描述 |
| 8 | TK-1031 揚言今天就請銀行止付 | system_issue/checkout_error · human · P3 | 當日期限是否算急迫 | **維持 P3**：急迫度看出發或使用時間，客戶設的回覆期限算影響程度 |
| 9 | TK-1019 飯店與網頁不符，揚言找消保官 | complaint/compensation_claim · human · P3 | 若仍在旅途中，應歸 trip_incident · P4 | **維持**：內文沒有在旅途中的訊號 |
| 10 | TK-1044 客服報錯價，要求退還 1,500 元 | complaint/compensation_claim · human · P3 | 小額求償是否也要 P3 | **維持**：求償類下限 P3，簡單好解釋 |
| 11 | TK-1028 護照英文名拼錯，兩週後出發 | order_change/data_correction · human · P2 | 可能無法登機，影響程度是否為 high | **改 P3**，影響程度 high 補上「可能導致無法成行」 |
| 12 | TK-1033 「可以退嗎」 | unclear/insufficient_info · auto · P2 | 模型兩次都判 cancel_policy；兩者 route 都是 auto | **維持** |
| 13 | TK-1047 記者採訪，週五截稿 | other/business · human · P1 | 有期限，排最後是否合理 | **維持 P1**：轉交公關，不佔客服佇列 |

---

## 5. 執行步驟（每步一個 commit）

### Step 1：spec 定義對齊

- **檔案**：`category-priority-spec.md`
- **內容**：
  - §1 route 原則改寫為原則 3；「需寫入系統、需調查或判斷責任、需供應商確認」改成「AI 無法決定內容」的具體情況。
  - §2 依 4.4 調整邊界：客訴補上「補償與安撫屬人的判斷」；影響程度 high 補上「可能導致無法成行」（若採 #11）。
  - §3、§4 寫入第 4.1 節的流程與風險分數；新增 `other/unclear`；移除「模型輸入包含進件時間」。
- **完成標準**：spec 能單獨解釋 4.4 每一筆的標註。
- **commit**：`docs(spec): align route definition and flow decisions`

### Step 2：修訂標準答案

- **檔案**：`poc/data/expected_labels.csv`
- **內容**：依 4.4 的決定修改；不為了提高分數而改。
- **commit**：`data(poc): revise expected labels after review`

### Step 3：前處理精簡

- **檔案**：`poc/pipeline/preprocess.py`
- **保留**：只讀前 6 欄、去除前後空白、移除 HTML 標籤（`<br>` 轉換行）。
- **移除**：NFKC 全形轉半形、簽名檔、HTML entity、縮排處理（樣本中沒有，或已經用不到）。
- **模型輸入**：移除進件時間，只保留主旨與內文。
- **commit**：`refactor(poc): keep only required preprocessing; drop created_at from model input`

### Step 4：分流流程

- **檔案**：`poc/config/routing.toml`、`poc/config/labels.toml`、`poc/pipeline/router.py`、`poc/triage.py`
- **內容**：
  - `routing.toml`：新增 `[risk]`（`w_c`、`w_u`、`w_i`、`threshold = 0.6`）、`classification_threshold = 0.5`、`level_conf_threshold = 0.70`；`[route]` 加入 `other/unclear = "human"`；`priority_fixed` 排除 `other/unclear`。
  - `labels.toml`：依 4.4 調整邊界；急迫度描述改為「信件中提到 72 小時內要出發或使用，或已在旅途中」。`other/unclear` **不放進模型選項**，只由 router 指派。
  - `router.py`：依 4.1 的 6 個步驟實作。
  - `triage.py`：模型錯誤寫入 `run.log`，包含題目、錯誤類型、重試次數。
- **完成標準**：mock 可以跑完；用上次 Clef 輸出重算，結果與 4.3 的 T = 0.6 那一列一致（再加上 D1 的效果）。
- **commit**：`feat(poc): weighted risk score routing and other/unclear for low confidence`

### Step 5：報表

- **檔案**：`poc/evaluate.py`、`poc/review_template.html`
- **內容**：
  - False Auto 不為 0 時，報表最上方顯示紅色警示，並列出 False Auto 的工單。
  - 評估把 `other/unclear` 分開計算：判斷不了的比例，以及有判斷時的準確率（4.3 第 6 點）。
  - 逐筆檢視加上風險分數欄位。
  - 資料發現依 Step 3 改寫：只列實際處理的項目；全形字、簽名檔等列為「觀察，不處理：模型可直接閱讀」。
- **commit**：`feat(poc): highlight false auto and align data findings`

### Step 6：README

- **檔案**：`poc/README.md`
- **內容**：
  - 流程圖換成作者版本，只補兩處文字：`Fail` 寫成「系統報錯：寫 log、轉人工」，`Map` 寫成「routing：對應表決定 route／priority」。
  - 新增「Pipeline 各模組」：`triage.py`、`preprocess.py`、`models.py`、`router.py`、`evaluate.py`、`review_template.html`、`labels.toml`、`routing.toml` 各自的職責、輸入輸出與串接方式。
  - 新增「分類邏輯」：3 題各問什麼、route 怎麼決定（細項對應表加上風險分數）、低信心去向、priority 怎麼算，並舉 2–3 個例子走一遍。
  - 新增「參數與 overfitting」：權重與閾值的設定理由、T 的試算表、為什麼不選 0.8。
  - 新增「為什麼不放進件時間」：急迫度只依信件中的相對日期判斷；精確的 72 小時由正式環境的訂單出發日計算；加入進件時間後信心下降，原因未確認前先不使用。
  - 前處理與資料發現依 Step 3 改寫。
- **commit**：`docs(poc): add module guide and classification logic`

### Step 7：answer 對齊

- **檔案**：`answer.md`
- **內容**：
  - Q2 §3 的 route 定義改為原則 3。
  - Q3 §1、§4 的轉人工條件改為第 4.1 節的版本（風險分數、`other/unclear`）。
  - Q3 §2 的流程圖精簡節點文字。
  - 全文檢查沒有工單 ID。
- **完成標準**：spec、`routing.toml`、`labels.toml`、answer、README 五處的 route 定義與轉人工條件一致。
- **commit**：`docs(answer): align route definition and flow with spec`

---

## 6. 驗證（需要作者用 Clef 實跑）

1. Step 4 完成後跑一次。**必要條件：False Auto = 0。** False Human 逐筆檢查，確認都屬於可以接受的保守判斷。
2. 對照組（選做）：用相同輸入，分別以上一版和這一版的 `labels.toml` 各跑一次，確認信心下降是不是「不含」的寫法造成的。若是，「不含」只寫在 spec，不放進給模型的描述。

## 7. 這一階段不做

- 權重搜尋（權重依原則固定為 1，見 4.3）。
- 合成測試資料。
- 文字關鍵字規則。
- 個資遮罩（假設地端部署）。
- 讀取 xlsx（內容與 CSV 相同）。
