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

FIELDS = ("category", "sub_category", "route")
_PII_RE = re.compile(r"\b[A-Z][12]\d{8}\b|\b09\d{8}\b|\b\d{3}-\d{10,14}\b")


def load_expected_labels(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {r["ticket_id"].strip(): {k: v.strip() for k, v in r.items()} for r in csv.DictReader(f)}


def compute_eval_metrics(decisions: list[TriageDecision], gold: dict[str, dict[str, str]]) -> dict[str, Any]:
    rows = [(d, gold[d.ticket_id]) for d in decisions if d.ticket_id in gold]
    n = len(rows) or 1
    acc = {f: round(sum(getattr(d, f) == g[f] for d, g in rows) / n * 100, 1) for f in FIELDS}
    unclear = [(d, g) for d, g in rows if d.category == "other" and d.sub_category == "unclear"]
    judged = [(d, g) for d, g in rows if (d, g) not in unclear]
    judged_ok = sum(d.sub_category == g["sub_category"] and d.category == g["category"] for d, g in judged)
    bins = {}
    for label, cond in (("≥ 0.70", lambda c: c >= 0.70), ("0.50 – 0.70", lambda c: 0.50 <= c < 0.70),
                        ("< 0.50（歸 other/unclear）", lambda c: c < 0.50)):
        sel = [(d, g) for d, g in rows if cond(d.confidence) and not d.reason.startswith("模型異常")]
        ok = sum(d.sub_category == g["sub_category"] for d, g in sel)
        bins[label] = {"n": len(sel), "acc": round(ok / len(sel) * 100, 1) if sel else None}
    return {
        "total": len(rows), "cat_acc": acc["category"], "sub_acc": acc["sub_category"],
        "route_acc": acc["route"],
        "false_auto": sum(d.route == "auto" and g["route"] == "human" for d, g in rows),
        "false_auto_ids": [d.ticket_id for d, g in rows if d.route == "auto" and g["route"] == "human"],
        "unclear_n": len(unclear),
        "judged_acc": round(judged_ok / len(judged) * 100, 1) if judged else 0.0,
        "false_human": sum(d.route == "human" and g["route"] == "auto" for d, g in rows),
        "conf_bins": bins,
    }


def find_data_issues(tickets: list[Ticket]) -> list[tuple[str, int, str]]:
    """資料發現：只列有實際處置的問題。"""
    out: list[tuple[str, int, str]] = []
    extra = sum(1 for t in tickets if t.extra_empty_cols)
    if extra:
        out.append(("試算表匯出後每列尾端多出空白欄位", extra, "只讀取前 6 個欄位"))
    html_n = sum(1 for t in tickets if t.had_html)
    if html_n:
        out.append(("HTML 標籤（如 <br>）", html_n, "移除標籤，<br> 轉換行"))
    pii = sum(1 for t in tickets if _PII_RE.search(t.body))
    if pii:
        out.append(("內文夾帶證號、手機或銀行帳號", pii, "模型地端部署、不出內網；log 不存信件全文"))
    names = Counter(t.customer_name for t in tickets)
    dup = sum(c for c in names.values() if c > 1)
    if dup:
        out.append(("同一寄件人再次來信催單", dup, "PoC 不合併；正式環境由工單系統以客戶 ID 判斷未結案件"))
    return out


def _bars(counts: list[tuple[str, int]], total: int) -> str:
    peak = max((c for _, c in counts), default=1) or 1
    rows = []
    for label, c in counts:
        tip = f"{label}：{c} 件（{c / total * 100:.1f}%）"
        rows.append(
            f'<div class="bar-row" data-tip="{html.escape(tip)}"><span class="bar-label">{html.escape(label)}</span>'
            f'<span class="bar-track"><span class="bar" style="width:{c / peak * 100:.1f}%"></span>'
            f'<span class="bar-val">{c}</span></span></div>'
        )
    return "".join(rows)


def _tile(label: str, value: Any, note: str = "", cls: str = "") -> str:
    return (f'<div class="tile {cls}"><div class="tile-label">{html.escape(label)}</div>'
            f'<div class="tile-value">{value}</div><div class="tile-note">{note}</div></div>')


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="plain"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def write_review_html(out_path: Path, tickets: list[Ticket], decisions: list[TriageDecision],
                      gold: dict[str, dict[str, str]], metrics: dict[str, Any] | None, model_name: str) -> None:
    n = len(decisions) or 1
    by_id = {t.ticket_id: t for t in tickets}
    routes = Counter(d.route for d in decisions)
    cats = Counter(d.category for d in decisions).most_common()
    subs = Counter(f"{d.category} / {d.sub_category}" for d in decisions).most_common()
    gate = 0.70
    urg = Counter(d.urgency if d.urgency_conf >= gate else "low" for d in decisions)
    imp = Counter(d.impact if d.impact_conf >= gate else "low" for d in decisions)
    human_pct = routes["human"] / n * 100

    tiles = [
        _tile("工單數", len(decisions)),
        _tile("需人工（human）", f"{human_pct:.0f}%", f"{routes['human']} 件"),
        _tile("可草擬（auto）", f"{100 - human_pct:.0f}%", f"{routes['auto']} 件"),
        _tile("平均處理時間", f"{sum(d.total_ms for d in decisions) / n / 1000:.1f}s", "每件，含 3 次模型呼叫"),
    ]
    eval_tiles, bins_html, eval_note = "", "", '<p class="muted">未提供標準標註，略過評估。</p>'
    if metrics:
        fa = metrics["false_auto"]
        eval_tiles = "".join([
            _tile("主類別準確率", f"{metrics['cat_acc']}%"),
            _tile("細項準確率", f"{metrics['sub_acc']}%"),
            _tile("route 準確率", f"{metrics['route_acc']}%"),
            _tile("判斷不了（other/unclear）", metrics["unclear_n"], "分類信心不足，交給人判斷"),
            _tile("有判斷時的細項準確率", f"{metrics['judged_acc']}%", "排除 other/unclear"),
            _tile("False Auto", f"{'✓' if fa == 0 else '✕'} {fa}", "應 human 卻判 auto，必須為 0",
                  "good" if fa == 0 else "critical"),
            _tile("False Human", metrics["false_human"], "應 auto 卻判 human（較保守）"),
        ])
        bins_html = _table(["分類信心", "件數", "細項準確率"],
                           [[k, v["n"], "–" if v["acc"] is None else f"{v['acc']}%"] for k, v in metrics["conf_bins"].items()])
        eval_note = ('<p class="muted">48 筆樣本也是設計類別時參考的資料，以上數字只代表開發集；'
                     '正式驗收需使用未參與設計的歷史工單。</p>')

    records = []
    for d in decisions:
        t, g = by_id[d.ticket_id], gold.get(d.ticket_id)
        diff = [f for f in FIELDS if g and getattr(d, f) != g[f]]
        records.append({
            "id": d.ticket_id, "created": t.created_at, "channel": t.channel, "subject": t.subject, "body": t.body,
            "rank": d.queue_rank, "cat": d.category, "sub": d.sub_category, "route": d.route,
            "conf": round(d.confidence, 2), "risk": round(d.risk, 2), "urg": d.urgency, "imp": d.impact, "reason": d.reason,
            "gold": {f: g[f] for f in FIELDS} if g else None, "diff": diff,
        })

    page = TEMPLATE
    for key, val in {
        "%%GENERATED%%": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "%%MODEL%%": html.escape(model_name),
        "%%TILES%%": "".join(tiles),
        "%%HUMAN_PCT%%": f"{human_pct:.1f}",
        "%%AUTO_PCT%%": f"{100 - human_pct:.1f}",
        "%%HUMAN_N%%": str(routes["human"]),
        "%%AUTO_N%%": str(routes["auto"]),
        "%%CAT_BARS%%": _bars(cats, n),
        "%%SUB_BARS%%": _bars(subs, n),
        "%%URG_BARS%%": _bars([(lv, urg[lv]) for lv in ("high", "medium", "low")], n),
        "%%IMP_BARS%%": _bars([(lv, imp[lv]) for lv in ("high", "medium", "low")], n),
        "%%ISSUES%%": _table(["發現", "件數", "處置"], [list(r) for r in find_data_issues(tickets)]),
        "%%EVAL_TILES%%": eval_tiles,
        "%%ALERT%%": (f'<div class="alert">✕ False Auto {metrics["false_auto"]} 筆：{"、".join(metrics["false_auto_ids"])}。'
                      "應由人處理的工單被判為 auto，上線前必須為 0。</div>") if metrics and metrics["false_auto"] else "",
        "%%BINS%%": bins_html,
        "%%EVAL_NOTE%%": eval_note,
        "%%DATA%%": json.dumps(records, ensure_ascii=False).replace("</", "<\\/"),
    }.items():
        page = page.replace(key, val)
    out_path.write_text(page, encoding="utf-8")


TEMPLATE = (Path(__file__).with_name("review_template.html")).read_text(encoding="utf-8")
