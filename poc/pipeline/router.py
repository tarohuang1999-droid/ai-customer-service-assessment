from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .models import DecisionModel
from .preprocess import Ticket, build_model_input

PRIORITY_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}  # P4 最高


@dataclass(slots=True)
class TriageDecision:
    ticket_id: str
    category: str
    sub_category: str
    route: str
    priority: str
    confidence: float
    urgency: str
    urgency_conf: float
    impact: str
    impact_conf: float
    reason: str
    model: str
    model_input: str = ""
    model_traces: list[dict[str, Any]] = field(default_factory=list)
    total_ms: float = 0.0


def triage_one(ticket: Ticket, model: DecisionModel, labels: dict[str, Any], routing: dict[str, Any],
               threshold: float | None = None) -> TriageDecision:
    """決策模型回答 3 題，再依 routing.toml 的對應表決定 route 與 priority。"""
    t0 = time.perf_counter()
    model_input = build_model_input(ticket, int(routing.get("max_body_chars", 300)))
    r = model.classify(model_input, labels)

    if r.error:  # fail-closed：模型異常一律轉人工
        return TriageDecision(ticket.ticket_id, "unclear", "insufficient_info", "human", "P3", 0.0,
                              "low", 0.0, "low", 0.0, f"模型異常轉人工：{r.error}", r.model_name,
                              model_input, r.model_traces, round((time.perf_counter() - t0) * 1000, 1))

    key = f"{r.category}/{r.sub_category}"

    # route：細項對應表；分類信心不足 -> human
    route = routing["route"][key]
    thr = threshold if threshold is not None else float(routing.get("confidence_threshold", 0.70))
    reason = f"分類信心 {r.confidence:.2f}"
    if r.confidence < thr:
        route = "human"
        reason += "；信心不足轉人工"

    # priority：急迫度 x 影響程度 -> 細項下限 -> 大類固定值
    priority = routing["priority_matrix"][r.urgent_level][r.impact_level]
    floor = routing.get("priority_floor", {}).get(key)
    if floor and PRIORITY_RANK[floor] > PRIORITY_RANK[priority]:
        priority = floor
    priority = routing.get("priority_fixed", {}).get(r.category, priority)

    return TriageDecision(
        ticket_id=ticket.ticket_id, category=r.category, sub_category=r.sub_category,
        route=route, priority=priority, confidence=r.confidence,
        urgency=r.urgent_level, urgency_conf=r.urgent_conf, impact=r.impact_level, impact_conf=r.impact_conf,
        reason=reason, model=r.model_name, model_input=model_input, model_traces=r.model_traces,
        total_ms=round((time.perf_counter() - t0) * 1000, 1),
    )
