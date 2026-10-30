from __future__ import annotations

import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any

from .models import DecisionModel
from .preprocess import Ticket, build_model_input

LEVEL_RANK = {"high": 2, "medium": 1, "low": 0}


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


def triage_one(ticket: Ticket, model: DecisionModel, labels: dict[str, Any], routing: dict[str, Any],
               threshold: float | None = None) -> TriageDecision:
    """決策模型回答 3 題，再依 routing.toml 決定 route。"""
    t0 = time.perf_counter()
    model_input = build_model_input(ticket, int(routing.get("max_body_chars", 300)))
    r = model.classify(model_input, labels)

    if r.error:  # fail-closed：模型異常一律轉人工
        return TriageDecision(ticket.ticket_id, ticket.created_at, "unclear", "insufficient_info", "human", 0.0,
                              "low", 0.0, "low", 0.0, f"模型異常轉人工：{r.error}", r.model_name,
                              model_input=model_input, model_traces=r.model_traces,
                              total_ms=round((time.perf_counter() - t0) * 1000, 1))

    key = f"{r.category}/{r.sub_category}"
    route = routing["route"][key]
    thr = threshold if threshold is not None else float(routing.get("confidence_threshold", 0.70))
    reason = f"分類信心 {r.confidence:.2f}"
    if r.confidence < thr:
        route = "human"
        reason += "；信心不足轉人工"

    return TriageDecision(
        ticket_id=ticket.ticket_id, created_at=ticket.created_at, category=r.category, sub_category=r.sub_category,
        route=route, confidence=r.confidence,
        urgency=r.urgent_level, urgency_conf=r.urgent_conf, impact=r.impact_level, impact_conf=r.impact_conf,
        reason=reason, model=r.model_name, model_input=model_input, model_traces=r.model_traces,
        total_ms=round((time.perf_counter() - t0) * 1000, 1),
    )


def assign_queue_rank(decisions: list[TriageDecision], level_conf_threshold: float = 0.70) -> list[TriageDecision]:
    """佇列排序：急迫度 → 影響程度 → 進件時間。程度信心不足時視為 low。回傳依排序後的清單。"""
    def level(name: str, conf: float) -> int:
        return LEVEL_RANK[name] if conf >= level_conf_threshold else 0

    def created(d: TriageDecision) -> datetime:
        try:
            return datetime.strptime(d.created_at, "%Y-%m-%d %H:%M")
        except ValueError:
            return datetime.max

    ordered = sorted(decisions, key=lambda d: (-level(d.urgency, d.urgency_conf),
                                               -level(d.impact, d.impact_conf), created(d)))
    for i, d in enumerate(ordered, 1):
        d.queue_rank = i
    return ordered
