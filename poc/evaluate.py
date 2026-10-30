from __future__ import annotations

import csv
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any

from pipeline.preprocess import Ticket
from pipeline.router import TriageDecision

ALL_CATEGORIES = [
    "product_inquiry",
    "order_info",
    "order_change",
    "order_refund",
    "complaint",
    "other_non_cs",
    "unknown",
]


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
    cat_ok = sub_ok = route_ok = prio_ok = false_auto = false_human = 0
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
        "route_acc": round(route_ok / total * 100, 1) if total else 0.0,
        "route_err_rate": round((total - route_ok) / total * 100, 1) if total else 0.0,
        "false_auto": false_auto,
        "false_human": false_human,
        "prio_ok": prio_ok,
        "prio_acc": round(prio_ok / total * 100, 1) if total else 0.0,
        "mismatches": mismatches,
    }


def write_review_html(
    out_path: str | Path,
    tickets: list[Ticket],
    decisions: list[TriageDecision],
    gold: dict[str, dict[str, str]],
    eval_metrics: dict[str, Any],
    prep_ms: float = 0.0,
) -> None:
    total = len(decisions)
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
                "urgent_level": d.urgent_level,
                "urgent_conf": d.urgent_conf,
                "impact_level": d.impact_level,
                "impact_conf": d.impact_conf,
                "total_ms": d.total_ms,
                "clf_ms": d.stage_classification_ms,
                "urg_ms": d.stage_urgent_ms,
                "imp_ms": d.stage_impact_ms,
                "reason": d.reason,
                "model": d.model,
                "tags": d.signal_tags,
                "gold_category": g.get("category", ""),
                "gold_sub": g.get("sub_category", ""),
                "gold_priority": g.get("priority", ""),
                "gold_route": g.get("route", ""),
                "all_match": bool(cat_match and sub_match and route_match and prio_match),
                "route_match": route_match,
                "is_false_auto": is_false_auto,
            }
        )

    cat_counts = Counter(d.category for d in decisions)
    prio_counts = Counter(d.priority for d in decisions)
    human_cnt = sum(1 for d in decisions if d.route == "human")
    auto_cnt = total - human_cnt

    sum_regex = sum(d.regex_ms for d in decisions)
    sum_clf = sum(d.stage_classification_ms for d in decisions)
    sum_urg = sum(d.stage_urgent_ms for d in decisions)
    sum_imp = sum(d.stage_impact_ms for d in decisions)
    sum_route = sum(d.router_ms for d in decisions)
    sum_total = prep_ms + sum(d.total_ms for d in decisions)

    cat_rows_html = []
    for cat in ALL_CATEGORIES:
        cnt = cat_counts.get(cat, 0)
        c_auto = sum(1 for d in decisions if d.category == cat and d.route == "auto")
        c_hum = sum(1 for d in decisions if d.category == cat and d.route == "human")
        cat_rows_html.append(
            f"<tr><td><code>{cat}</code></td><td>{cnt} ({cnt / total * 100:.1f}%)</td>"
            f"<td>{c_auto}</td><td>{c_hum}</td></tr>"
        )

    prio_defs = [
        ("P4", "超重要急件（72小時內出發急件、旅途中危機、帳號鎖定待付款）"),
        ("P3", "高影響與爭議（服務瑕疵求償、大額 >3萬、升級字眼、重複催單）"),
        ("P2", "一般標準件（售前諮詢、訂單與規定查詢、一般退改）"),
        ("P1", "低優先（廣告、測試單、非客服轉介）"),
    ]
    prio_rows_html = [
        f"<tr><td><span class='badge prio-{p}'>{p}</span></td><td>{desc}</td>"
        f"<td>{prio_counts.get(p, 0)} ({prio_counts.get(p, 0) / total * 100:.1f}%)</td></tr>"
        for p, desc in prio_defs
    ]

    stage_rows_html = [
        f"<tr><td><code>stage=preprocess</code></td><td>{prep_ms:.1f} ms</td><td>{prep_ms / total:.2f} ms</td></tr>",
        f"<tr><td><code>stage=regex</code></td><td>{sum_regex:.1f} ms</td><td>{sum_regex / total:.2f} ms</td></tr>",
        f"<tr><td><code>stage=classification</code></td><td>{sum_clf:.1f} ms</td><td>{sum_clf / total:.1f} ms</td></tr>",
        f"<tr><td><code>stage=urgent_level</code></td><td>{sum_urg:.1f} ms</td><td>{sum_urg / total:.1f} ms</td></tr>",
        f"<tr><td><code>stage=impact_level</code></td><td>{sum_imp:.1f} ms</td><td>{sum_imp / total:.1f} ms</td></tr>",
        f"<tr><td><code>stage=router</code></td><td>{sum_route:.1f} ms</td><td>{sum_route / total:.2f} ms</td></tr>",
        f"<tr><td><strong>總計 (total)</strong></td><td><strong>{sum_total / 1000:.2f} s</strong></td><td><strong>{sum_total / total:.1f} ms</strong></td></tr>",
    ]

    data_json = json.dumps(records, ensure_ascii=False)
    metrics_json = json.dumps(eval_metrics, ensure_ascii=False)
    model_label = html.escape(decisions[0].model if decisions else "N/A")
    cat_options_html = "\n".join(f'<option value="{c}">{c}</option>' for c in ALL_CATEGORIES)

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
  .container {{ max-width: 1440px; margin: 0 auto; padding: 20px 24px; }}
  .section-box {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; margin-bottom: 20px; }}
  .section-title {{ margin: 0 0 14px 0; font-size: 16px; font-weight: 700; color: #0f172a; border-left: 4px solid var(--primary); padding-left: 10px; display: flex; justify-content: space-between; align-items: center; }}
  .section-title span.sub {{ font-size: 12px; font-weight: 400; color: var(--muted); }}
  .summary-kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 16px; }}
  .kpi {{ background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }}
  .kpi .k-label {{ font-size: 12px; color: var(--muted); }}
  .kpi .k-val {{ font-size: 20px; font-weight: 700; margin-top: 2px; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; }}
  .summary-grid h3 {{ margin: 0 0 8px 0; font-size: 13px; color: #334155; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }}
  .card {{ background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; position: relative; }}
  .card .rank {{ font-size: 11px; font-weight: 700; color: var(--primary); margin-bottom: 4px; }}
  .card .label {{ font-size: 13px; font-weight: 600; color: #1e293b; margin-bottom: 4px; }}
  .card .value {{ font-size: 24px; font-weight: 700; }}
  .card .sub {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
  .ok {{ color: var(--success); }}
  .bad {{ color: var(--danger); }}
  .toolbar {{ background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; margin-bottom: 14px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }}
  .toolbar select, .toolbar input {{ padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; background: #fff; }}
  .toolbar input {{ flex: 1; min-width: 200px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; font-size: 13px; }}
  th, td {{ padding: 9px 12px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
  th {{ background: #f1f5f9; font-weight: 600; color: #334155; }}
  tr:hover {{ background: #f8fafc; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }}
  .route-auto {{ background: #dcfce7; color: #166534; }}
  .route-human {{ background: #fee2e2; color: #991b1b; }}
  .prio-P4 {{ background: #dc2626; color: #fff; }}
  .prio-P3 {{ background: #f97316; color: #fff; }}
  .prio-P2 {{ background: #e2e8f0; color: #334155; }}
  .prio-P1 {{ background: #f1f5f9; color: #64748b; }}
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
  <div class="meta">Model: <strong>{model_label}</strong> | Total: {len(records)} tickets (Priority: P1=低優先 ~ P4=超重要急件)</div>
</header>
<div class="container">

  <!-- Section 1: Triage Summary -->
  <section class="section-box">
    <h2 class="section-title">
      <span>Section 1 — Triage Summary（分流執行摘要）</span>
      <span class="sub">總耗時 {sum_total / 1000:.2f} s ｜ 單筆平均 {sum_total / total:.1f} ms</span>
    </h2>
    <div class="summary-kpis">
      <div class="kpi">
        <div class="k-label">總處理工單數</div>
        <div class="k-val">{total} 筆</div>
      </div>
      <div class="kpi">
        <div class="k-label">需真人處理 (route = human)</div>
        <div class="k-val">{human_cnt} 筆 ({human_cnt / total * 100:.1f}%)</div>
      </div>
      <div class="kpi">
        <div class="k-label">可自動草擬／模板／歸檔 (route = auto)</div>
        <div class="k-val">{auto_cnt} 筆 ({auto_cnt / total * 100:.1f}%)</div>
      </div>
      <div class="kpi">
        <div class="k-label">推論模型與架構</div>
        <div class="k-val">{model_label}</div>
      </div>
    </div>
    <div class="summary-grid">
      <div>
        <h3>1. 主類別分佈（Category Distribution）</h3>
        <table>
          <thead><tr><th>Category</th><th>筆數 (佔比)</th><th>auto</th><th>human</th></tr></thead>
          <tbody>{''.join(cat_rows_html)}</tbody>
        </table>
      </div>
      <div>
        <h3>2. 優先級分佈（P4=超重要急件 -> P1=低優先）</h3>
        <table>
          <thead><tr><th>Priority</th><th>定義</th><th>筆數 (佔比)</th></tr></thead>
          <tbody>{''.join(prio_rows_html)}</tbody>
        </table>
      </div>
      <div>
        <h3>3. 各階段執行耗時（Stage Latency Breakdown）</h3>
        <table>
          <thead><tr><th>執行階段 (stage)</th><th>總耗時</th><th>單筆平均</th></tr></thead>
          <tbody>{''.join(stage_rows_html)}</tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- Section 2: All Metrics Sorted by Importance -->
  <section class="section-box">
    <h2 class="section-title">
      <span>Section 2 — All Metrics Sorted by Importance（評估指標，依重要性排序）</span>
      <span class="sub">依據 Q2/Q4 驗收門檻由高風險紅線至輔助指標排序</span>
    </h2>
    <div class="cards" id="metric-cards"></div>
  </section>

  <!-- Section 3: Result Table -->
  <section class="section-box">
    <h2 class="section-title">
      <span>Section 3 — Result Table（工單分流結果檢視表）</span>
      <span class="sub" id="row-count"></span>
    </h2>
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
        {cat_options_html}
      </select>
      <select id="f-prio">
        <option value="all">全部優先級 (Priority)</option>
        <option value="P4">P4 超重要急件</option>
        <option value="P3">P3 高影響爭議</option>
        <option value="P2">P2 一般標準</option>
        <option value="P1">P1 低優先</option>
      </select>
      <input type="text" id="f-search" placeholder="搜尋單號、客戶姓名、主旨、內文或判斷原因..." />
    </div>
    <table>
      <thead>
        <tr>
          <th style="width:90px;">工單</th>
          <th style="width:34%;">主旨 / 內文 / 抽取訊號</th>
          <th style="width:18%;">預測 Category / Sub</th>
          <th style="width:100px;">Route / Prio</th>
          <th style="width:155px;">信心度 &amp; 耗時</th>
          <th>分流依據 (Reason)</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </section>

</div>
<script>
const RECORDS = {data_json};
const METRICS = {metrics_json};

function renderCards() {{
  // Sorted strictly by operational criticality / Gate importance
  const cards = [
    {{
      rank: 'PRIORITY #1 ｜ 安全紅線 Gate',
      label: '高風險誤放行 (False Auto)',
      val: METRICS.false_auto + ' 件',
      sub: '驗收門檻：= 0 件（應轉人工卻誤判 auto）',
      cls: METRICS.false_auto === 0 ? 'ok' : 'bad'
    }},
    {{
      rank: 'PRIORITY #2 ｜ 路由品質 Gate',
      label: '分流錯誤率 (Route Error Rate)',
      val: METRICS.route_err_rate + '%',
      sub: `驗收門檻：≤ 10%（一致 ${{METRICS.route_ok}} / ${{METRICS.total}} 筆）`,
      cls: METRICS.route_err_rate <= 10 ? 'ok' : 'bad'
    }},
    {{
      rank: 'PRIORITY #3 ｜ 細項精準度',
      label: '細項正確率 (Sub-category Acc)',
      val: METRICS.sub_acc + '%',
      sub: `命中 ${{METRICS.sub_ok}} / ${{METRICS.total}} 筆（14 合併選項單選）`,
      cls: METRICS.sub_acc >= 90 ? 'ok' : ''
    }},
    {{
      rank: 'PRIORITY #4 ｜ 主類別精準度',
      label: '主類別正確率 (Category Acc)',
      val: METRICS.cat_acc + '%',
      sub: `驗收門檻：≥ 90%（命中 ${{METRICS.cat_ok}} / ${{METRICS.total}} 筆）`,
      cls: METRICS.cat_acc >= 90 ? 'ok' : 'bad'
    }},
    {{
      rank: 'PRIORITY #5 ｜ 佇列排序品質',
      label: '優先級一致率 (Priority Acc)',
      val: METRICS.prio_acc + '%',
      sub: `P1~P4 一致 ${{METRICS.prio_ok}} / ${{METRICS.total}} 筆`,
      cls: METRICS.prio_acc >= 90 ? 'ok' : ''
    }},
    {{
      rank: 'PRIORITY #6 ｜ 防禦性兜底統計',
      label: '保守轉人工數 (False Human)',
      val: METRICS.false_human + ' 件',
      sub: '低信心度 (< 0.70) 安全轉由真人處理',
      cls: ''
    }}
  ];
  document.getElementById('metric-cards').innerHTML = cards.map(c => `
    <div class="card">
      <div class="rank">${{c.rank}}</div>
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
          <strong>conf: ${{r.confidence.toFixed(2)}}</strong>
          <div style="font-size:11px;color:#64748b;margin-top:4px;">
            urgent: ${{esc(r.urgent_level)}} (${{r.urgent_conf.toFixed(2)}})<br>
            impact: ${{esc(r.impact_level)}} (${{r.impact_conf.toFixed(2)}})<br>
            耗時: ${{r.total_ms.toFixed(0)}}ms (clf:${{r.clf_ms.toFixed(0)}}/urg:${{r.urg_ms.toFixed(0)}}/imp:${{r.imp_ms.toFixed(0)}})
          </div>
        </td>
        <td>
          <div class="reason-text">${{esc(r.reason)}}</div>
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
