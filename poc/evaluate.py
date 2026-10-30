from __future__ import annotations

import csv
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any

from pipeline.preprocess import Ticket
from pipeline.router import TriageDecision


def load_expected_labels(gold_csv: str | Path) -> dict[str, dict[str, str]]:
    gold: dict[str, dict[str, str]] = {}
    with Path(gold_csv).open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            tid = row["ticket_id"].strip()
            gold[tid] = {k: v.strip() for k, v in row.items()}
    return gold


def compute_eval_metrics(
    decisions: list[TriageDecision],
    gold: dict[str, dict[str, str]],
) -> dict[str, Any]:
    total = len(decisions)
    cat_ok = 0
    sub_ok = 0
    route_ok = 0
    prio_ok = 0
    false_auto = 0
    false_human = 0
    mismatches: list[dict[str, Any]] = []

    for d in decisions:
        g = gold.get(d.ticket_id)
        if not g:
            continue
        c_match = d.category == g["category"]
        s_match = d.sub_category == g["sub_category"]
        r_match = d.route == g["route"]
        p_match = d.priority == g["priority"]

        if c_match:
            cat_ok += 1
        if s_match:
            sub_ok += 1
        if r_match:
            route_ok += 1
        else:
            if g["route"] == "human" and d.route == "auto":
                false_auto += 1
            elif g["route"] == "auto" and d.route == "human":
                false_human += 1
        if p_match:
            prio_ok += 1

        if not (c_match and s_match and r_match and p_match):
            mismatches.append(
                {
                    "ticket_id": d.ticket_id,
                    "pred_category": d.category,
                    "gold_category": g["category"],
                    "pred_sub": d.sub_category,
                    "gold_sub": g["sub_category"],
                    "pred_route": d.route,
                    "gold_route": g["route"],
                    "pred_priority": d.priority,
                    "gold_priority": g["priority"],
                    "confidence": d.confidence,
                    "reason": d.reason,
                }
            )

    return {
        "total": total,
        "cat_ok": cat_ok,
        "cat_acc": round(cat_ok / total * 100, 1) if total else 0.0,
        "sub_ok": sub_ok,
        "sub_acc": round(sub_ok / total * 100, 1) if total else 0.0,
        "route_ok": route_ok,
        "route_err_rate": round((total - route_ok) / total * 100, 1) if total else 0.0,
        "false_auto": false_auto,
        "false_human": false_human,
        "prio_ok": prio_ok,
        "prio_acc": round(prio_ok / total * 100, 1) if total else 0.0,
        "mismatches": mismatches,
    }


def write_summary_md(
    out_path: str | Path,
    tickets: list[Ticket],
    decisions: list[TriageDecision],
    eval_metrics: dict[str, Any] | None = None,
) -> None:
    total = len(decisions)
    cat_counts = Counter(d.category for d in decisions)
    sub_counts = Counter(f"{d.category} / {d.sub_category}" for d in decisions)
    route_counts = Counter(d.route for d in decisions)
    prio_counts = Counter(d.priority for d in decisions)

    extra_col_tickets = sum(1 for t in tickets if t.extra_empty_cols > 0)
    fw_tickets = [t.ticket_id for t in tickets if t.had_fullwidth_alnum]
    repeat_tickets = [t.ticket_id for t in tickets if t.is_repeat_customer]
    pii_tickets = [d.ticket_id for d in decisions if "inline_pii" in d.signal_tags]
    short_tickets = [d.ticket_id for d in decisions if d.sub_category == "insufficient_info"]
    spam_tickets = [d.ticket_id for d in decisions if d.sub_category == "spam_or_test"]

    human_cnt = route_counts.get("human", 0)
    auto_cnt = route_counts.get("auto", 0)

    lines = [
        "# 工單分流執行摘要（Execution Summary）",
        "",
        f"- **總處理工單數**：{total} 筆",
        f"- **使用模型**：`{decisions[0].model if decisions else 'N/A'}`",
        f"- **分流比例**：",
        f"  - `route = human`（需真人處理）：**{human_cnt} 筆（{human_cnt / total * 100:.1f}%）**",
        f"  - `route = auto`（可自動草擬／固定模板／規則歸檔）：**{auto_cnt} 筆（{auto_cnt / total * 100:.1f}%）**",
        "",
        "## 1. 主類別分佈（Category Distribution）",
        "",
        "| 主類別 (`category`) | 筆數 | 佔比 | `auto` 筆數 | `human` 筆數 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]

    for cat in ["product_inquiry", "order_service", "refund_change", "complaint", "other_non_cs", "unknown"]:
        cnt = cat_counts.get(cat, 0)
        c_auto = sum(1 for d in decisions if d.category == cat and d.route == "auto")
        c_hum = sum(1 for d in decisions if d.category == cat and d.route == "human")
        lines.append(f"| `{cat}` | {cnt} | {cnt / total * 100:.1f}% | {c_auto} | {c_hum} |")

    lines.extend(
        [
            "",
            "## 2. 細項分類分佈（Sub-category Distribution）",
            "",
            "| 主類別 / 細項 (`category / sub_category`) | 筆數 | 佔比 |",
            "| --- | ---: | ---: |",
        ]
    )
    for k, cnt in sorted(sub_counts.items()):
        lines.append(f"| `{k}` | {cnt} | {cnt / total * 100:.1f}% |")

    lines.extend(
        [
            "",
            "## 3. 優先級分佈（Priority Distribution）",
            "",
            "| 優先級 (`priority`) | 筆數 | 佔比 |",
            "| --- | ---: | ---: |",
        ]
    )
    for p in ["P1", "P2", "P3", "P4"]:
        cnt = prio_counts.get(p, 0)
        lines.append(f"| `{p}` | {cnt} | {cnt / total * 100:.1f}% |")

    lines.extend(
        [
            "",
            "## 4. 資料裡發現的問題與處置統計",
            "",
            "| 資料問題類型 | 影響筆數 | 代表工單單號 | Pipeline 處置方式 |",
            "| --- | ---: | --- | --- |",
            f"| CSV 尾端多出 20 個空白欄位 | {extra_col_tickets} 筆 | 全部工單（`TK-1001`–`TK-1048`） | 讀取時僅截取前 6 個有效欄位並去除首尾空白 |",
            f"| 全形數字／英文字母混用 | {len(fw_tickets)} 筆 | {', '.join(f'`{x}`' for x in fw_tickets)} | 以 `unicodedata.normalize('NFKC')` 正規化為半形，確保金額與日期 Regex 不漏抓 |",
            f"| 外部博弈廣告與系統測試單 | {len(spam_tickets)} 筆 | {', '.join(f'`{x}`' for x in spam_tickets)} | 前置規則直接標記 `other_non_cs / spam_or_test`（`route=auto`, `P4`） |",
            f"| 內文過短缺乏訂單與訴求上下文 | {len(short_tickets)} 筆 | {', '.join(f'`{x}`' for x in short_tickets)} | 前置規則標記 `unknown / insufficient_info`（`route=auto` 套用固定補件模板） |",
            f"| 同一客戶重複進件催單 | {len(repeat_tickets)} 筆 | {', '.join(f'`{x}`' for x in repeat_tickets)} | 跨單比對 `customer_name` 關聯前案（`TK-1013` -> `TK-1031`），強制 `route=human`, `P2` |",
            f"| 信件內文直接夾帶高敏個資 | {len(pii_tickets)} 筆 | {', '.join(f'`{x}`' for x in pii_tickets)} | Regex 偵測標記 `inline_pii`（身分證、手機、銀行帳號），呼應 Q1/Q3 個資邊界規範 |",
        ]
    )

    if eval_metrics:
        lines.extend(
            [
                "",
                "## 5. 與標準標註（Golden Set 48 筆）比對指標",
                "",
                f"- **主類別正確率（Category Accuracy）**：{eval_metrics['cat_ok']}/{eval_metrics['total']}（**{eval_metrics['cat_acc']}%**）",
                f"- **細項正確率（Sub-category Accuracy）**：{eval_metrics['sub_ok']}/{eval_metrics['total']}（**{eval_metrics['sub_acc']}%**）",
                f"- **分流錯誤率（Route Error Rate）**：{eval_metrics['total'] - eval_metrics['route_ok']}/{eval_metrics['total']}（**{eval_metrics['route_err_rate']}%**，門檻 ≤ 10%）",
                f"- **高風險誤放行（False Auto）**：**{eval_metrics['false_auto']} 件**（紅線門檻 = 0 件）",
                f"- **優先級一致率（Priority Accuracy）**：{eval_metrics['prio_ok']}/{eval_metrics['total']}（**{eval_metrics['prio_acc']}%**）",
            ]
        )

    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_eval_report_md(out_path: str | Path, eval_metrics: dict[str, Any]) -> None:
    lines = [
        "# 模型與分流規則評估報告（Evaluation Report）",
        "",
        "| 指標 | 結果 | Q2/Q4 驗收門檻 | 是否達標 |",
        "| --- | ---: | ---: | :---: |",
        f"| 主類別正確率（Category Accuracy） | {eval_metrics['cat_ok']}/{eval_metrics['total']} ({eval_metrics['cat_acc']}%) | ≥ 90% | {'PASS' if eval_metrics['cat_acc'] >= 90 else 'CHECK'} |",
        f"| 細項正確率（Sub-category Accuracy） | {eval_metrics['sub_ok']}/{eval_metrics['total']} ({eval_metrics['sub_acc']}%) | - | - |",
        f"| 分流錯誤率（Route Error Rate） | {eval_metrics['route_err_rate']}% | ≤ 10% | {'PASS' if eval_metrics['route_err_rate'] <= 10 else 'FAIL'} |",
        f"| 高風險誤放行（False Auto） | {eval_metrics['false_auto']} 件 | = 0 件 | {'PASS' if eval_metrics['false_auto'] == 0 else 'FAIL'} |",
        f"| 保守轉人工（False Human） | {eval_metrics['false_human']} 件 | 允許保守轉人工 | PASS |",
        f"| 優先級一致率（Priority Accuracy） | {eval_metrics['prio_ok']}/{eval_metrics['total']} ({eval_metrics['prio_acc']}%) | - | - |",
        "",
    ]

    mismatches = eval_metrics["mismatches"]
    if not mismatches:
        lines.append("## 不一致明細\n\n全部 48 筆工單之預測與標準標註完全一致。")
    else:
        lines.extend(
            [
                f"## 不一致明細（共 {len(mismatches)} 筆）",
                "",
                "| 工單 | 預測 Category/Sub | 標準 Category/Sub | 預測 Route/Prio | 標準 Route/Prio | 信心度 | 判斷依據 |",
                "| --- | --- | --- | --- | --- | ---: | --- |",
            ]
        )
        for m in mismatches:
            lines.append(
                f"| `{m['ticket_id']}` | `{m['pred_category']}/{m['pred_sub']}` | `{m['gold_category']}/{m['gold_sub']}` | "
                f"`{m['pred_route']}/{m['pred_priority']}` | `{m['gold_route']}/{m['gold_priority']}` | {m['confidence']:.2f} | {m['reason']} |"
            )

    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_review_html(
    out_path: str | Path,
    tickets: list[Ticket],
    decisions: list[TriageDecision],
    gold: dict[str, dict[str, str]],
    eval_metrics: dict[str, Any],
) -> None:
    ticket_map = {t.ticket_id: t for t in tickets}
    records: list[dict[str, Any]] = []
    for d in decisions:
        t = ticket_map[d.ticket_id]
        g = gold.get(d.ticket_id, {})
        cat_match = d.category == g.get("category", d.category)
        sub_match = d.sub_category == g.get("sub_category", d.sub_category)
        route_match = d.route == g.get("route", d.route)
        prio_match = d.priority == g.get("priority", d.priority)
        is_false_auto = g.get("route") == "human" and d.route == "auto"
        records.append(
            {
                "ticket_id": d.ticket_id,
                "created_at": t.created_at,
                "channel": t.channel,
                "customer_name": t.customer_name,
                "subject": t.subject,
                "body": t.body,
                "pred_category": d.category,
                "pred_sub": d.sub_category,
                "pred_priority": d.priority,
                "pred_route": d.route,
                "confidence": d.confidence,
                "cat_conf": d.category_conf,
                "sub_conf": d.sub_category_conf,
                "urgent_p": d.is_urgent_prob,
                "impact_p": d.is_high_impact_prob,
                "reason": d.reason,
                "model": d.model,
                "tags": d.signal_tags,
                "gold_category": g.get("category", ""),
                "gold_sub": g.get("sub_category", ""),
                "gold_priority": g.get("priority", ""),
                "gold_route": g.get("route", ""),
                "gold_notes": g.get("notes", ""),
                "all_match": bool(cat_match and sub_match and route_match and prio_match),
                "route_match": route_match,
                "is_false_auto": is_false_auto,
            }
        )

    data_json = json.dumps(records, ensure_ascii=False)
    metrics_json = json.dumps(eval_metrics, ensure_ascii=False)
    model_label = html.escape(decisions[0].model if decisions else "N/A")

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>T 旅遊工單分流 PoC — Review & Eval 檢視器</title>
<style>
  :root {{
    --bg: #f8fafc; --card: #ffffff; --border: #e2e8f0; --text: #0f172a; --muted: #64748b;
    --primary: #2563eb; --success: #16a34a; --warn: #d97706; --danger: #dc2626;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; background: var(--bg); color: var(--text); }}
  header {{ background: #0f172a; color: #fff; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }}
  header h1 {{ margin: 0; font-size: 18px; }}
  header .meta {{ font-size: 13px; color: #94a3b8; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 20px 24px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 18px; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }}
  .card .label {{ font-size: 12px; color: var(--muted); margin-bottom: 4px; }}
  .card .value {{ font-size: 24px; font-weight: 700; }}
  .card .sub {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}
  .ok {{ color: var(--success); }}
  .bad {{ color: var(--danger); }}
  .toolbar {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }}
  .toolbar select, .toolbar input {{ padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }}
  .toolbar input {{ flex: 1; min-width: 200px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; font-size: 13px; }}
  th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
  th {{ background: #f1f5f9; font-weight: 600; color: #334155; }}
  tr:hover {{ background: #f8fafc; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }}
  .route-auto {{ background: #dcfce7; color: #166534; }}
  .route-human {{ background: #fee2e2; color: #991b1b; }}
  .prio-P1 {{ background: #dc2626; color: #fff; }}
  .prio-P2 {{ background: #f97316; color: #fff; }}
  .prio-P3 {{ background: #e2e8f0; color: #334155; }}
  .prio-P4 {{ background: #f1f5f9; color: #64748b; }}
  .tag {{ display: inline-block; background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; border-radius: 4px; padding: 1px 6px; font-size: 11px; margin: 1px 2px; }}
  .mismatch {{ background: #fff7ed; }}
  .diff {{ color: var(--danger); font-weight: 600; font-size: 12px; display: block; margin-top: 2px; }}
  .body-text {{ color: #334155; margin-top: 4px; line-height: 1.45; }}
  .reason-text {{ color: #475569; font-size: 12px; line-height: 1.4; }}
</style>
</head>
<body>
<header>
  <h1>T 旅遊工單分流 PoC — Review & Eval 檢視器</h1>
  <div class="meta">Model: <strong>{model_label}</strong> | Total: {len(records)} tickets</div>
</header>
<div class="container">
  <div class="cards" id="metric-cards"></div>
  <div class="toolbar">
    <select id="f-status">
      <option value="all">全部狀態 (All)</option>
      <option value="mismatch">僅看預測與標註不一致 (Mismatch)</option>
      <option value="false_auto">僅看高風險誤放行 (False Auto)</option>
      <option value="low_conf">僅看低信心度 (&lt; 0.70)</option>
    </select>
    <select id="f-route">
      <option value="all">全部 Route</option>
      <option value="auto">route = auto</option>
      <option value="human">route = human</option>
    </select>
    <select id="f-cat">
      <option value="all">全部主類別 (Category)</option>
      <option value="product_inquiry">product_inquiry</option>
      <option value="order_service">order_service</option>
      <option value="refund_change">refund_change</option>
      <option value="complaint">complaint</option>
      <option value="other_non_cs">other_non_cs</option>
      <option value="unknown">unknown</option>
    </select>
    <select id="f-prio">
      <option value="all">全部優先級 (Priority)</option>
      <option value="P1">P1 緊急</option>
      <option value="P2">P2 高</option>
      <option value="P3">P3 一般</option>
      <option value="P4">P4 低</option>
    </select>
    <input type="text" id="f-search" placeholder="搜尋單號、客戶姓名、主旨、內文或判斷原因..." />
    <span id="row-count" style="font-size:12px;color:#64748b;"></span>
  </div>
  <table>
    <thead>
      <tr>
        <th style="width:90px;">工單</th>
        <th style="width:32%;">主旨 / 內文 / 抽取訊號</th>
        <th style="width:18%;">預測 Category / Sub</th>
        <th style="width:110px;">Route / Prio</th>
        <th style="width:110px;">分層信心度</th>
        <th>分流依據 (Reason) &amp; 標準標註備註</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>
<script>
const RECORDS = {data_json};
const METRICS = {metrics_json};

function renderCards() {{
  const humanCnt = RECORDS.filter(r => r.pred_route === 'human').length;
  const autoCnt = RECORDS.length - humanCnt;
  const cards = [
    {{ label: 'Category 正確率', val: METRICS.cat_acc + '%', sub: `${{METRICS.cat_ok}} / ${{METRICS.total}} 筆`, cls: METRICS.cat_acc >= 90 ? 'ok' : '' }},
    {{ label: 'Sub-category 正確率', val: METRICS.sub_acc + '%', sub: `${{METRICS.sub_ok}} / ${{METRICS.total}} 筆`, cls: '' }},
    {{ label: 'Route 分流錯誤率', val: METRICS.route_err_rate + '%', sub: `門檻 ≤ 10% (一致 ${{METRICS.route_ok}}/${{METRICS.total}})`, cls: METRICS.route_err_rate <= 10 ? 'ok' : 'bad' }},
    {{ label: '高風險誤放行 (False Auto)', val: METRICS.false_auto + ' 件', sub: '紅線門檻 = 0 件', cls: METRICS.false_auto === 0 ? 'ok' : 'bad' }},
    {{ label: '需人工比例 (route=human)', val: (humanCnt / RECORDS.length * 100).toFixed(1) + '%', sub: `human: ${{humanCnt}} / auto: ${{autoCnt}}`, cls: '' }},
    {{ label: 'Priority 一致率', val: METRICS.prio_acc + '%', sub: `${{METRICS.prio_ok}} / ${{METRICS.total}} 筆`, cls: '' }}
  ];
  document.getElementById('metric-cards').innerHTML = cards.map(c => `
    <div class="card">
      <div class="label">${{c.label}}</div>
      <div class="value ${{c.cls}}">${{c.val}}</div>
      <div class="sub">${{c.sub}}</div>
    </div>
  `).join('');
}}

function esc(s) {{
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function renderTable() {{
  const st = document.getElementById('f-status').value;
  const rt = document.getElementById('f-route').value;
  const cat = document.getElementById('f-cat').value;
  const prio = document.getElementById('f-prio').value;
  const q = document.getElementById('f-search').value.trim().toLowerCase();

  const filtered = RECORDS.filter(r => {{
    if (st === 'mismatch' && r.all_match) return false;
    if (st === 'false_auto' && !r.is_false_auto) return false;
    if (st === 'low_conf' && r.confidence >= 0.70) return false;
    if (rt !== 'all' && r.pred_route !== rt) return false;
    if (cat !== 'all' && r.pred_category !== cat) return false;
    if (prio !== 'all' && r.pred_priority !== prio) return false;
    if (q) {{
      const hay = `${{r.ticket_id}} ${{r.customer_name}} ${{r.subject}} ${{r.body}} ${{r.pred_category}} ${{r.pred_sub}} ${{r.reason}}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }}
    return true;
  }});

  document.getElementById('row-count').textContent = `顯示 ${{filtered.length}} / ${{RECORDS.length}} 筆`;
  document.getElementById('tbody').innerHTML = filtered.map(r => {{
    const catDiff = r.pred_category !== r.gold_category ? `<span class="diff">標準: ${{esc(r.gold_category)}}</span>` : '';
    const subDiff = r.pred_sub !== r.gold_sub ? `<span class="diff">標準: ${{esc(r.gold_sub)}}</span>` : '';
    const routeDiff = r.pred_route !== r.gold_route ? `<span class="diff">標準: ${{esc(r.gold_route)}}</span>` : '';
    const prioDiff = r.pred_priority !== r.gold_priority ? `<span class="diff">標準: ${{esc(r.gold_priority)}}</span>` : '';
    const tagsHtml = (r.tags || []).map(t => `<span class="tag">${{esc(t)}}</span>`).join('');
    return `
      <tr class="${{r.all_match ? '' : 'mismatch'}}">
        <td>
          <strong>${{esc(r.ticket_id)}}</strong><br>
          <span style="color:#64748b;font-size:11px;">${{esc(r.channel)}}<br>${{esc(r.customer_name)}}</span>
        </td>
        <td>
          <strong>${{esc(r.subject)}}</strong>
          <div class="body-text">${{esc(r.body)}}</div>
          <div style="margin-top:4px;">${{tagsHtml}}</div>
        </td>
        <td>
          <div><code>${{esc(r.pred_category)}}</code>${{catDiff}}</div>
          <div style="margin-top:4px;color:#475569;"><code>${{esc(r.pred_sub)}}</code>${{subDiff}}</div>
        </td>
        <td>
          <span class="badge route-${{esc(r.pred_route)}}">${{esc(r.pred_route)}}</span>${{routeDiff}}
          <div style="margin-top:6px;"><span class="badge prio-${{esc(r.pred_priority)}}">${{esc(r.pred_priority)}}</span>${{prioDiff}}</div>
        </td>
        <td>
          <strong>${{r.confidence.toFixed(2)}}</strong>
          <div style="font-size:11px;color:#64748b;margin-top:4px;">
            大項: ${{r.cat_conf.toFixed(2)}}<br>
            細項: ${{r.sub_conf.toFixed(2)}}<br>
            急件p: ${{r.urgent_p.toFixed(2)}}<br>
            影響p: ${{r.impact_p.toFixed(2)}}
          </div>
        </td>
        <td>
          <div class="reason-text">${{esc(r.reason)}}</div>
          <div style="margin-top:4px;font-size:11px;color:#64748b;">標註說明：${{esc(r.gold_notes)}}</div>
        </td>
      </tr>
    `;
  }}).join('');
}}

['f-status','f-route','f-cat','f-prio','f-search'].forEach(id => {{
  document.getElementById(id).addEventListener('input', renderTable);
}});
renderCards();
renderTable();
</script>
</body>
</html>
"""
    Path(out_path).write_text(html_doc, encoding="utf-8")
