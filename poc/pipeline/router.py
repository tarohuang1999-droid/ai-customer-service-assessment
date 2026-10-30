from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .models import DecisionModel
from .preprocess import Ticket, build_model_input

LEVEL_RANK = {"high": 2, "medium": 1, "low": 0}
UNCLEAR = ("other", "unclear")


@dataclass(slots=True)
class TriageDecision:
    ticket_id: str
    created_at: str
    category: str
    sub_category: str
    route: str
    confidence: float
    urgency: str
    urgency_conf: float
    impact: str
    impact_conf: float
    reason: str
    model: str
    queue_rank: int = 0
    model_input: str = ""
    model_traces: list[dict[str, Any]] = field(default_factory=list)
    total_ms: float = 0.0


def triage_one(ticket: Ticket, model: DecisionModel, labels: dict[str, Any], routing: dict[str, Any]) -> TriageDecision:
    """決策模型回答 3 題 → 分類信心不足歸 other/unclear → 條件規則決定 route。"""
    t0 = time.perf_counter()
    model_input = build_model_input(ticket, int(routing.get("max_body_chars", 300)))
    r = model.classify(model_input, labels)

    def done(category: str, sub_category: str, route: str, reason: str) -> TriageDecision:
        return TriageDecision(
            ticket_id=ticket.ticket_id, created_at=ticket.created_at,
            category=category, sub_category=sub_category, route=route, confidence=r.confidence,
            urgency=r.urgent_level, urgency_conf=r.urgent_conf, impact=r.impact_level, impact_conf=r.impact_conf,
            reason=reason, model=r.model_name, model_input=model_input, model_traces=r.model_traces,
            total_ms=round((time.perf_counter() - t0) * 1000, 1),
        )

    # 模型異常：fail-closed，一律轉人工；錯誤細節由 triage.py 寫入 log
    if r.error:
        return done(*UNCLEAR, "human", f"模型異常轉人工：{r.error}")

    # 1. 分類信心不足：系統判斷不了，歸 other/unclear
    threshold = float(routing.get("classification_threshold", 0.5))
    if r.confidence < threshold:
        return done(*UNCLEAR, "human",
                    f"分類信心 {r.confidence:.2f} < {threshold:.2f}，歸為 other/unclear（模型原判 {r.category}/{r.sub_category}）")

    # 2. 條件規則：細項在 auto 白名單內，且急迫度、影響程度都在允許清單內 -> auto；其餘一律 human
    key = f"{r.category}/{r.sub_category}"
    cond = routing["auto"].get(key)
    if cond is None:
        route, why = "human", f"{key} 不在 auto 白名單"
    elif r.urgent_level not in cond["urgency"]:
        route, why = "human", f"急迫度 {r.urgent_level} 不在 auto 條件"
    elif r.impact_level not in cond["impact"]:
        route, why = "human", f"影響程度 {r.impact_level} 不在 auto 條件"
    else:
        route, why = "auto", "符合 auto 條件"
    return done(r.category, r.sub_category, route, f"分類信心 {r.confidence:.2f}；{why}")


def assign_queue_rank(decisions: list[TriageDecision], level_conf_threshold: float = 0.70) -> list[TriageDecision]:
    """佇列排序：模型異常置頂 → human 在 auto 前 → 急迫度 → 影響程度 → 進件時間。
    程度信心不足時，排序視為 low（分流仍採模型選的等級）。回傳依排序後的清單。"""
    def level(name: str, conf: float) -> int:
        return LEVEL_RANK.get(name, 2) if conf >= level_conf_threshold else 0  # 未知等級保守視為 high

    def created(d: TriageDecision) -> datetime:
        try:
            return datetime.strptime(d.created_at, "%Y-%m-%d %H:%M")
        except ValueError:
            return datetime.max

    ordered = sorted(decisions, key=lambda d: (not d.reason.startswith("模型異常"), d.route != "human",
                                               -level(d.urgency, d.urgency_conf),
                                               -level(d.impact, d.impact_conf), created(d)))
    for i, d in enumerate(ordered, 1):
        d.queue_rank = i
    return ordered
