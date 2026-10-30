# 模型與分流規則評估報告（Evaluation Report）

| 指標 | 結果 | Q2/Q4 驗收門檻 | 是否達標 |
| --- | ---: | ---: | :---: |
| 主類別正確率（Category Accuracy） | 46/48 (95.8%) | ≥ 90% | PASS |
| 細項正確率（Sub-category Accuracy） | 46/48 (95.8%) | - | - |
| 分流錯誤率（Route Error Rate） | 6.2% | ≤ 10% | PASS |
| 高風險誤放行（False Auto） | 0 件 | = 0 件 | PASS |
| 保守轉人工（False Human） | 3 件 | 允許保守轉人工 | PASS |
| 優先級一致率（Priority Accuracy） | 43/48 (89.6%) | - | - |

## 不一致明細（共 9 筆）

| 工單 | 預測 Category/Sub | 標準 Category/Sub | 預測 Route/Prio | 標準 Route/Prio | 信心度 | 判斷依據 |
| --- | --- | --- | --- | --- | ---: | --- |
| `TK-1013` | `complaint/service_or_billing_dispute` | `complaint/service_or_billing_dispute` | `human/P1` | `human/P2` | 0.84 | 分層模型(llamacpp-clef)：complaint(p=0.84) -> service_or_billing_dispute(p=0.84, 預設=human)；硬性規則：退改/爭議金額 33,100 元 > 30,000 元；硬性規則：含客訴升級/消保官/媒體/止付字眼；模型緊急度判定 P1 (urgent_p=0.72) |
| `TK-1014` | `refund_change/refund_change_policy_general` | `refund_change/refund_change_policy_general` | `human/P3` | `auto/P3` | 0.40 | 分層模型(llamacpp-clef)：refund_change(p=0.40) -> refund_change_policy_general(p=0.96, 預設=auto)；信心門檻攔截：最低階層信心 0.40 < 0.70 |
| `TK-1019` | `complaint/service_or_billing_dispute` | `complaint/service_or_billing_dispute` | `human/P1` | `human/P2` | 0.78 | 分層模型(llamacpp-clef)：complaint(p=0.78) -> service_or_billing_dispute(p=0.89, 預設=human)；硬性規則：含客訴升級/消保官/媒體/止付字眼；硬性規則：同客重複進件催單；模型緊急度判定 P1 (urgent_p=0.80) |
| `TK-1027` | `order_service/order_status_and_points` | `order_service/order_status_and_points` | `human/P3` | `auto/P3` | 0.64 | 分層模型(llamacpp-clef)：order_service(p=0.64) -> order_status_and_points(p=0.74, 預設=auto)；信心門檻攔截：最低階層信心 0.64 < 0.70 |
| `TK-1028` | `refund_change/order_modification` | `refund_change/order_modification` | `human/P1` | `human/P3` | 0.24 | 分層模型(llamacpp-clef)：refund_change(p=0.24) -> order_modification(p=0.93, 預設=human)；信心門檻攔截：最低階層信心 0.24 < 0.70；模型緊急度判定 P1 (urgent_p=0.90) |
| `TK-1030` | `complaint/service_or_billing_dispute` | `order_service/account_and_pricing_issue` | `human/P2` | `human/P3` | 0.17 | 分層模型(llamacpp-clef)：complaint(p=0.17) -> service_or_billing_dispute(p=0.69, 預設=human)；信心門檻攔截：最低階層信心 0.17 < 0.70 |
| `TK-1031` | `complaint/service_or_billing_dispute` | `complaint/service_or_billing_dispute` | `human/P1` | `human/P2` | 0.84 | 分層模型(llamacpp-clef)：complaint(p=0.84) -> service_or_billing_dispute(p=0.84, 預設=human)；硬性規則：退改/爭議金額 33,100 元 > 30,000 元；硬性規則：含客訴升級/消保官/媒體/止付字眼；硬性規則：同客重複進件催單；模型緊急度判定 P1 (urgent_p=0.81) |
| `TK-1038` | `refund_change/refund_change_policy_general` | `refund_change/refund_change_policy_general` | `human/P3` | `auto/P3` | 0.64 | 分層模型(llamacpp-clef)：refund_change(p=0.64) -> refund_change_policy_general(p=0.90, 預設=auto)；信心門檻攔截：最低階層信心 0.64 < 0.70 |
| `TK-1045` | `product_inquiry/product_spec_and_price` | `refund_change/order_modification` | `human/P3` | `human/P3` | 0.11 | 分層模型(llamacpp-clef)：product_inquiry(p=0.11) -> product_spec_and_price(p=0.28, 預設=auto)；信心門檻攔截：最低階層信心 0.11 < 0.70 |
