from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .models import DecisionModel
from .preprocess import Ticket
from .signals import Signals, build_model_input

PRIORITY_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}  # P4 highest


def _max_priority(*levels: str) -> str:
    return max(levels, key=lambda p: PRIORITY_RANK[p])


@dataclass(slots=True)
class TriageDecision:
    ticket_id: str
    category: str
    sub_category: str
    priority: str
    route: str
    confidence: float
    reason: str
    model: str
    urgent_level: str = "low"
    urgent_conf: float = 0.0
    impact_level: str = "low"
    impact_conf: float = 0.0
    rules_hit: list[str] = field(default_factory=list)
    signal_tags: list[str] = field(default_factory=list)
    model_input: str = ""
    model_traces: list[dict[str, Any]] = field(default_factory=list)
    total_ms: float = 0.0


def _rule_hits(signals: Signals) -> list[str]:
    hits = []
    if signals.is_urgent_72h:
        hits.append("urgent_72h")
    if signals.is_high_amount:
        hits.append("high_amount")
    if signals.has_escalation:
        hits.append("escalation")
    if signals.is_repeat_followup:
        hits.append("repeat_followup")
    return hits


def triage_one(
    ticket: Ticket,
    signals: Signals,
    model: DecisionModel,
    labels_cfg: dict[str, Any],
    route_cfg: dict[str, Any],
    threshold: float | None = None,
) -> TriageDecision:
    """Route one ticket in 4 steps: rule archive -> model (3 questions) -> hard rules -> confidence gate."""
    t0 = time.perf_counter()
    model_input = build_model_input(ticket, int(route_cfg.get("max_body_chars", 300)))
    tags = signals.tags()

    # Step 1: irrelevant mail (ads / test / auto-reply) is archived by rule; no model call.
    if signals.is_irrelevant:
        return TriageDecision(
            ticket_id=ticket.ticket_id, category="other", sub_category="irrelevant",
            priority="P1", route="auto", confidence=1.0,
            reason=f"規則歸檔：{signals.irrelevant_kind}", model="rule",
            signal_tags=tags, model_input=model_input,
            total_ms=round((time.perf_counter() - t0) * 1000, 1),
        )

    # Step 2: decision model answers classification / urgency / impact.
    clf = model.classify(model_input, labels_cfg)
    if clf.error:
        return TriageDecision(
            ticket_id=ticket.ticket_id, category="unclear", sub_category="insufficient_info",
            priority="P3", route="human", confidence=0.0,
            reason=f"模型異常轉人工：{clf.error}", model=clf.model_name,
            signal_tags=tags, model_input=model_input, model_traces=clf.model_traces,
            total_ms=round((time.perf_counter() - t0) * 1000, 1),
        )

    option = labels_cfg["classification"]["options"][f"{clf.category}/{clf.sub_category}"]
    route = str(option["route"])

    level_thr = float(route_cfg.get("level_conf_threshold", 0.70))
    urgency = clf.urgent_level if clf.urgent_conf >= level_thr else "low"
    impact = clf.impact_level if clf.impact_conf >= level_thr else "low"
    priority = _max_priority(route_cfg["priority_matrix"][urgency][impact], str(option["priority"]))

    notes: list[str] = []

    # Step 3: hard rules force human and raise priority.
    rules_cfg = route_cfg["rules"]
    hits = _rule_hits(signals)
    for rule in hits:
        route = "human"
        priority = _max_priority(priority, rules_cfg[rule]["min_priority"])
    if hits:
        notes.append("規則：" + "、".join(rules_cfg[r]["label"] for r in hits))

    # Step 4: low classification confidence -> human.
    conf_thr = float(threshold if threshold is not None else route_cfg.get("confidence_threshold", 0.70))
    if clf.confidence < conf_thr:
        route = "human"
        notes.append("信心不足轉人工")

    if clf.category in route_cfg.get("fixed_p1_categories", ["other"]):
        priority = "P1"

    return TriageDecision(
        ticket_id=ticket.ticket_id,
        category=clf.category,
        sub_category=clf.sub_category,
        priority=priority,
        route=route,
        confidence=clf.confidence,
        reason="；".join([f"分類信心 {clf.confidence:.2f}", *notes]),
        model=clf.model_name,
        urgent_level=clf.urgent_level,
        urgent_conf=clf.urgent_conf,
        impact_level=clf.impact_level,
        impact_conf=clf.impact_conf,
        rules_hit=hits,
        signal_tags=tags,
        model_input=model_input,
        model_traces=clf.model_traces,
        total_ms=round((time.perf_counter() - t0) * 1000, 1),
    )
