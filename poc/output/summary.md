# 工單分流執行摘要（Execution Summary）

- **總處理工單數**：48 筆
- **使用模型**：`llamacpp-clef`
- **分流比例**：
  - `route = human`（需真人處理）：**32 筆（66.7%）**
  - `route = auto`（可自動草擬／固定模板／規則歸檔）：**16 筆（33.3%）**

## 1. 主類別分佈（Category Distribution）

| 主類別 (`category`) | 筆數 | 佔比 | `auto` 筆數 | `human` 筆數 |
| --- | ---: | ---: | ---: | ---: |
| `product_inquiry` | 9 | 18.8% | 4 | 5 |
| `order_service` | 9 | 18.8% | 6 | 3 |
| `refund_change` | 12 | 25.0% | 1 | 11 |
| `complaint` | 10 | 20.8% | 2 | 8 |
| `other_non_cs` | 7 | 14.6% | 2 | 5 |
| `unknown` | 1 | 2.1% | 1 | 0 |

## 2. 細項分類分佈（Sub-category Distribution）

| 主類別 / 細項 (`category / sub_category`) | 筆數 | 佔比 |
| --- | ---: | ---: |
| `complaint / pure_complaint` | 2 | 4.2% |
| `complaint / service_or_billing_dispute` | 8 | 16.7% |
| `order_service / account_and_pricing_issue` | 1 | 2.1% |
| `order_service / document_reissue_and_invoice` | 5 | 10.4% |
| `order_service / order_status_and_points` | 3 | 6.2% |
| `other_non_cs / b2b_media_hr_referral` | 5 | 10.4% |
| `other_non_cs / spam_or_test` | 2 | 4.2% |
| `product_inquiry / customization_request` | 3 | 6.2% |
| `product_inquiry / policy_and_regulation` | 2 | 4.2% |
| `product_inquiry / product_spec_and_price` | 4 | 8.3% |
| `refund_change / order_cancellation_refund` | 4 | 8.3% |
| `refund_change / order_modification` | 5 | 10.4% |
| `refund_change / refund_change_policy_general` | 3 | 6.2% |
| `unknown / insufficient_info` | 1 | 2.1% |

## 3. 優先級分佈（Priority Distribution）

| 優先級 (`priority`) | 筆數 | 佔比 |
| --- | ---: | ---: |
| `P1` | 8 | 16.7% |
| `P2` | 5 | 10.4% |
| `P3` | 28 | 58.3% |
| `P4` | 7 | 14.6% |

## 4. 資料裡發現的問題與處置統計

| 資料問題類型 | 影響筆數 | 代表工單單號 | Pipeline 處置方式 |
| --- | ---: | --- | --- |
| CSV 尾端多出 20 個空白欄位 | 48 筆 | 全部工單（`TK-1001`–`TK-1048`） | 讀取時僅截取前 6 個有效欄位並去除首尾空白 |
| 全形數字／英文字母混用 | 2 筆 | `TK-1007`, `TK-1035` | 以 `unicodedata.normalize('NFKC')` 正規化為半形，確保金額與日期 Regex 不漏抓 |
| 外部博弈廣告與系統測試單 | 2 筆 | `TK-1008`, `TK-1041` | 前置規則直接標記 `other_non_cs / spam_or_test`（`route=auto`, `P4`） |
| 內文過短缺乏訂單與訴求上下文 | 1 筆 | `TK-1033` | 前置規則標記 `unknown / insufficient_info`（`route=auto` 套用固定補件模板） |
| 同一客戶重複進件催單 | 1 筆 | `TK-1031` | 跨單比對 `customer_name` 關聯前案（`TK-1013` -> `TK-1031`），強制 `route=human`, `P2` |
| 信件內文直接夾帶高敏個資 | 4 筆 | `TK-1005`, `TK-1012`, `TK-1023`, `TK-1039` | Regex 偵測標記 `inline_pii`（身分證、手機、銀行帳號），呼應 Q1/Q3 個資邊界規範 |

## 5. 與標準標註（Golden Set 48 筆）比對指標

- **主類別正確率（Category Accuracy）**：46/48（**95.8%**）
- **細項正確率（Sub-category Accuracy）**：46/48（**95.8%**）
- **分流錯誤率（Route Error Rate）**：3/48（**6.2%**，門檻 ≤ 10%）
- **高風險誤放行（False Auto）**：**0 件**（紅線門檻 = 0 件）
- **優先級一致率（Priority Accuracy）**：43/48（**89.6%**）
