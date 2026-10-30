"""Evaluation against expected_labels.csv and the single-file review.html report."""
from __future__ import annotations

import csv
import html
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from pipeline.preprocess import Ticket
from pipeline.router import TriageDecision

PRIORITIES = ["P4", "P3", "P2", "P1"]
CLEANING_LABELS = {
    "fullwidth": "全形英數字（已轉半形）",
    "html_tag": "HTML 標籤（如 <br>，已清除）",
    "html_entity": "HTML entity（已解碼）",
    "signature": "手機或郵件簽名檔（已移除）",
    "quoted_line": "引用回覆行（已移除）",
    "quoted_original": "原始郵件引用（已移除）",
}


def load_expected_labels(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {r["ticket_id"].strip(): {k: v.strip() for k, v in r.items()} for r in csv.DictReader(f)}


def compute_eval_metrics(decisions: list[TriageDecision], gold: dict[str, dict[str, str]]) -> dict[str, Any]:
    rows = [(d, gold[d.ticket_id]) for d in decisions if d.ticket_id in gold]
    n = len(rows) or 1

    def acc(field: str) -> float:
        return round(sum(getattr(d, field) == g[field] for d, g in rows) / n * 100, 1)

    # Confidence bins only for tickets the model classified (rule-archived tickets excluded).
    bins: dict[str, list[int]] = {"≥ 0.70": [0, 0], "< 0.70": [0, 0]}
    for d, g in rows:
        if d.model == "rule":
            continue
        key = "≥ 0.70" if d.confidence >= 0.70 else "< 0.70"
        bins[key][0] += 1
        bins[key][1] += d.sub_category == g["sub_category"]

    return {
        "total": len(rows),
        "cat_acc": acc("category"),
        "sub_acc": acc("sub_category"),
        "route_acc": acc("route"),
        "prio_acc": acc("priority"),
        "false_auto": sum(d.route == "auto" and g["route"] == "human" for d, g in rows),
        "false_human": sum(d.route == "human" and g["route"] == "auto" for d, g in rows),
        "conf_bins": {k: {"n": v[0], "acc": round(v[1] / v[0] * 100, 1) if v[0] else None} for k, v in bins.items()},
    }


def find_data_issues(tickets: list[Ticket], decisions: list[TriageDecision]) -> list[tuple[str, int, str]]:
    """Return (issue, count, handling) rows for the data-quality section."""
    issues: list[tuple[str, int, str]] = []
    extra = sum(1 for t in tickets if t.extra_empty_cols)
    if extra:
        issues.append(("CSV 每列尾端多出空白欄位", extra, "只讀取前 6 個欄位"))
    flags = Counter(f for t in tickets for f in t.cleaning_flags)
    for key, label in CLEANING_LABELS.items():
        if flags[key]:
            issues.append((label, flags[key], "前處理正規化"))
    kinds = Counter(d.reason.split("：", 1)[1] for d in decisions if d.model == "rule")
    for kind, cnt in kinds.items():
        issues.append((f"非客服信件：{kind}", cnt, "規則歸檔為 other/irrelevant，不呼叫模型"))
    repeat = sum(1 for t in tickets if t.is_repeat_customer)
    if repeat:
        issues.append(("同一寄件人再次來信", repeat, "標記重複催單，轉人工並調升優先級；正式環境改用客戶 ID"))
    pii = sum(1 for d in decisions if "has_inline_pii" in d.signal_tags)
    if pii:
        issues.append(("內文夾帶個資（證號、手機、帳號）", pii, "只標記，交由外部個資遮罩系統處理"))
    english = sum(1 for t in tickets if not re.search(r"[一-鿿]", t.body))
    if english:
        issues.append(("英文信件", english, "直接送模型分類，不另做翻譯"))
    short = sum(1 for t in tickets if len(t.body) < 10)
    if short:
        issues.append(("內文少於 10 字", short, "由模型判斷，看不出訴求時歸 unclear/insufficient_info"))
    return issues


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def write_review_html(out_path: Path, tickets: list[Ticket], decisions: list[TriageDecision],
                      gold: dict[str, dict[str, str]], metrics: dict[str, Any] | None, model_name: str) -> None:
    n = len(decisions)
    by_id = {t.ticket_id: t for t in tickets}
    route_cnt = Counter(d.route for d in decisions)
    cat_cnt = Counter(d.category for d in decisions)
    sub_cnt = Counter((d.category, d.sub_category) for d in decisions)
    prio_cnt = Counter(d.priority for d in decisions)

    summary = [
        ["工單數", n],
        ["需人工（route = human）", f"{route_cnt['human']}（{route_cnt['human'] / n * 100:.1f}%）"],
        ["可草擬（route = auto）", f"{route_cnt['auto']}（{route_cnt['auto'] / n * 100:.1f}%）"],
        ["平均處理時間", f"{sum(d.total_ms for d in decisions) / n:.0f} ms／件"],
    ]
    cat_rows = [[c, s, cnt, f"{cnt / n * 100:.1f}%"] for (c, s), cnt in sorted(sub_cnt.items())]
    cat_total_rows = [[c, cnt, f"{cnt / n * 100:.1f}%"] for c, cnt in cat_cnt.most_common()]
    prio_rows = [[p, prio_cnt[p]] for p in PRIORITIES]
    issue_rows = [list(r) for r in find_data_issues(tickets, decisions)]

    eval_html = "<p>未提供標準標註，略過評估。</p>"
    if metrics:
        eval_html = _table(["指標", "結果"], [
            ["主類別準確率", f"{metrics['cat_acc']}%"],
            ["細項準確率", f"{metrics['sub_acc']}%"],
            ["route 準確率", f"{metrics['route_acc']}%"],
            ["priority 準確率", f"{metrics['prio_acc']}%"],
            ["False Auto（應 human 卻判 auto，必須為 0）", metrics["false_auto"]],
            ["False Human（應 auto 卻判 human）", metrics["false_human"]],
        ]) + "<h3>分類信心分箱（檢驗 0.70 門檻）</h3>" + _table(
            ["分類信心", "件數", "細項準確率"],
            [[k, v["n"], "-" if v["acc"] is None else f"{v['acc']}%"] for k, v in metrics["conf_bins"].items()],
        ) + "<p class='note'>48 筆樣本同時是設計類別時參考的資料，以上數字只代表開發集表現；正式驗收需使用未參與設計的歷史工單。</p>"

    records = []
    for d in decisions:
        t, g = by_id[d.ticket_id], gold.get(d.ticket_id, {})
        ok = None if not g else all(getattr(d, f) == g[f] for f in ("category", "sub_category", "route", "priority"))
        records.append({
            "id": d.ticket_id, "subject": t.subject, "body": t.body,
            "pred": f"{d.category}/{d.sub_category}", "route": d.route, "priority": d.priority,
            "conf": round(d.confidence, 2), "urgency": d.urgent_level, "impact": d.impact_level,
            "gold": f"{g['category']}/{g['sub_category']} · {g['route']} · {g['priority']}" if g else "",
            "ok": ok, "reason": d.reason,
        })

    page = TEMPLATE.format(
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"), model=html.escape(model_name),
        summary=_table(["項目", "數值"], summary),
        categories=_table(["主類別", "件數", "比例"], cat_total_rows),
        subcategories=_table(["主類別", "細項", "件數", "比例"], cat_rows),
        priorities=_table(["優先級（P4 最高）", "件數"], prio_rows),
        issues=_table(["發現", "件數", "處置"], issue_rows),
        evaluation=eval_html,
        records=json.dumps(records, ensure_ascii=False).replace("</", "<\\/"),
    )
    out_path.write_text(page, encoding="utf-8")


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8"><title>工單分流 Review</title>
<style>
body{{font-family:-apple-system,"PingFang TC","Noto Sans TC",sans-serif;margin:32px;color:#1f2328;max-width:1280px}}
h1{{font-size:22px}} h2{{font-size:17px;margin-top:32px;border-bottom:1px solid #d0d7de;padding-bottom:4px}} h3{{font-size:14px}}
table{{border-collapse:collapse;font-size:13px;margin:8px 0}} th,td{{border:1px solid #d0d7de;padding:5px 9px;text-align:left;vertical-align:top}}
th{{background:#f6f8fa}} .grid{{display:flex;gap:28px;flex-wrap:wrap}} .note,.meta{{color:#656d76;font-size:12px}}
.bad{{background:#fff1f0}} .human{{color:#cf222e;font-weight:600}} .auto{{color:#1a7f37;font-weight:600}}
.controls{{display:flex;gap:8px;margin:8px 0}} input,select{{padding:4px 6px;font-size:13px}} .body{{color:#656d76;max-width:380px}}
</style></head><body>
<h1>工單分流 Review</h1>
<p class="meta">產生時間 {generated} · 模型 {model}</p>
<h2>1. 執行摘要</h2>
<div class="grid"><div>{summary}</div><div>{categories}</div><div>{priorities}</div></div>
<h3>細項分佈</h3>{subcategories}
<h2>2. 資料發現與處置</h2>{issues}
<h2>3. 評估（對照 expected_labels.csv）</h2>{evaluation}
<h2>4. 逐筆檢視</h2>
<div class="controls">
<input id="q" placeholder="搜尋 ID、主旨、內文、類別">
<select id="route"><option value="">全部 route</option><option>human</option><option>auto</option></select>
<select id="match"><option value="">全部</option><option value="bad">只看不一致</option></select>
</div>
<table><thead><tr><th>ID</th><th>主旨 / 內文</th><th>預測</th><th>route</th><th>priority</th><th>急迫 / 影響</th><th>標準答案</th><th>reason</th></tr></thead>
<tbody id="rows"></tbody></table>
<script>
const DATA = {records};
const esc = s => String(s).replace(/[&<>"]/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}})[c]);
function render() {{
  const q = document.getElementById("q").value.toLowerCase();
  const r = document.getElementById("route").value, m = document.getElementById("match").value;
  document.getElementById("rows").innerHTML = DATA.filter(d =>
    (!q || [d.id, d.subject, d.body, d.pred].join(" ").toLowerCase().includes(q)) &&
    (!r || d.route === r) && (!m || d.ok === false)
  ).map(d => `<tr class="${{d.ok === false ? "bad" : ""}}"><td>${{esc(d.id)}}</td>
    <td><b>${{esc(d.subject)}}</b><div class="body">${{esc(d.body)}}</div></td>
    <td>${{esc(d.pred)}}<br><span class="meta">信心 ${{d.conf}}</span></td>
    <td class="${{d.route}}">${{d.route}}</td><td>${{d.priority}}</td><td>${{d.urgency}} / ${{d.impact}}</td>
    <td>${{esc(d.gold)}}</td><td>${{esc(d.reason)}}</td></tr>`).join("");
}}
["q", "route", "match"].forEach(id => document.getElementById(id).addEventListener("input", render));
render();
</script></body></html>
"""
