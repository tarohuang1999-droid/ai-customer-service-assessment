from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .models import ClassificationResult, DecisionModel
from .preprocess import Ticket
from .signals import Signals, build_structured_state


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
    regex_ms: float = 0.0
    stage_classification_ms: float = 0.0
    stage_urgent_ms: float = 0.0
    stage_impact_ms: float = 0.0
    router_ms: float = 0.0
    total_ms: float = 0.0
    signal_tags: list[str] = field(default_factory=list)
    structured_state: str = ""
    model_traces: list[dict[str, Any]] = field(default_factory=list)


def triage_one(
    ticket: Ticket,
    signals: Signals,
    regex_ms: float,
    model: DecisionModel,
    labels_cfg: dict[str, Any],
    route_cfg: dict[str, Any],
    threshold_override: float | None = None,
) -> TriageDecision:
    t_start = time.perf_counter()
    max_body = int(route_cfg.get("max_body_chars", 300))
    state_str = build_structured_state(ticket, signals, max_body_chars=max_body)
    tags = signals.active_tags()

    # 1. Pre-rules: Spam / Test -> P1 (Low)
    if signals.is_spam or signals.is_test:
        kind = "系統測試單" if signals.is_test else "外部推銷/博弈廣告"
        r_ms = round((time.perf_counter() - t_start) * 1000, 2)
        return TriageDecision(
            ticket_id=ticket.ticket_id,
            category="other_non_cs",
            sub_category="spam_or_test",
            priority="P1",
            route="auto",
            confidence=1.0,
            reason=f"規則前置攔截：{kind}（P1 低優先直接歸檔）",
            model="rule-precheck",
            regex_ms=regex_ms,
            router_ms=r_ms,
            total_ms=round(regex_ms + r_ms, 2),
            signal_tags=tags,
            structured_state=state_str,
        )

    # 2. Pre-rules: Insufficient info (extremely short body) -> P2 (Standard)
    if signals.is_short_insufficient:
        r_ms = round((time.perf_counter() - t_start) * 1000, 2)
        return TriageDecision(
            ticket_id=ticket.ticket_id,
            category="unknown",
            sub_category="insufficient_info",
            priority="P2",
            route="auto",
            confidence=1.0,
            reason="規則前置攔截：內文過短且缺訂單與訴求（套用固定補件模板）",
            model="rule-precheck",
            regex_ms=regex_ms,
            router_ms=r_ms,
            total_ms=round(regex_ms + r_ms, 2),
            signal_tags=tags,
            structured_state=state_str,
        )

    # 3. 3-Stage Decision Model (classification, urgent_level, impact_level)
    clf: ClassificationResult = model.classify(state_str, labels_cfg)
    t_route = time.perf_counter()
    if clf.error:
        r_ms = round((time.perf_counter() - t_route) * 1000, 2)
        tot_ms = round(
            regex_ms + clf.stage_classification_ms + clf.stage_urgent_ms + clf.stage_impact_ms + r_ms, 1
        )
        return TriageDecision(
            ticket_id=ticket.ticket_id,
            category="unknown",
            sub_category="insufficient_info",
            priority="P3",
            route="human",
            confidence=0.0,
            reason=f"Fail-closed 模型異常轉人工：{clf.error}",
            model=clf.model_name,
            regex_ms=regex_ms,
            stage_classification_ms=clf.stage_classification_ms,
            stage_urgent_ms=clf.stage_urgent_ms,
            stage_impact_ms=clf.stage_impact_ms,
            router_ms=r_ms,
            total_ms=tot_ms,
            signal_tags=tags,
            structured_state=state_str,
            model_traces=clf.model_traces,
        )

    pair_key = f"{clf.category}/{clf.sub_category}"
    default_route = str(labels_cfg["classification"]["options"][pair_key]["route"])
    route = default_route
    reasons: list[str] = [
        f"模型({clf.model_name})：{clf.category}/{clf.sub_category}(conf={clf.confidence:.2f}, 預設={default_route}) "
        f"| urgent={clf.urgent_level}({clf.urgent_conf:.2f}) | impact={clf.impact_level}({clf.impact_conf:.2f})"
    ]

    # 4. Hard deterministic overrides (route = human is sticky)
    high_amt = int(route_cfg.get("high_amount_threshold", 30000))
    if signals.max_amount > high_amt and signals.is_financial_context:
        route = "human"
        reasons.append(f"硬性規則：退改/爭議金額 {signals.max_amount:,} 元 > {high_amt:,} 元")
    if signals.has_escalation:
        route = "human"
        reasons.append("硬性規則：含客訴升級/消保官/媒體/止付字眼")
    if signals.is_urgent_72h:
        route = "human"
        reasons.append("硬性規則：72小時內急件/旅途中危機/帳號鎖定待付款")
    if signals.is_repeat_followup:
        route = "human"
        reasons.append("硬性規則：同客重複進件催單")
    if signals.has_external_policy_change:
        route = "human"
        reasons.append("硬性規則：涉及外部最新簽證/法規變動無明確依據")

    # 5. Confidence threshold check (default 0.70)
    conf_thresh = float(
        threshold_override if threshold_override is not None else route_cfg.get("confidence_threshold", 0.70)
    )
    if clf.confidence < conf_thresh:
        route = "human"
        reasons.append(f"信心門檻攔截：分類信心 {clf.confidence:.2f} < {conf_thresh:.2f}")

    # 6. Priority determination (P1=Low -> P2=Standard -> P3=High Impact -> P4=Critical)
    p_rules = route_cfg.get("priority_rules", {})
    urg_thresh = float(route_cfg.get("urgency_conf_threshold", 0.70))
    imp_thresh = float(route_cfg.get("impact_conf_threshold", 0.70))

    if clf.category in p_rules.get("p1_categories", ["other_non_cs"]):
        priority = "P1"
    elif signals.is_urgent_72h or (clf.urgent_level == "high" and clf.urgent_conf >= urg_thresh and route == "human"):
        priority = "P4"
        if not signals.is_urgent_72h:
            reasons.append(f"模型判定緊急度 P4 (urgent_level=high, conf={clf.urgent_conf:.2f})")
    elif (
        (signals.max_amount > high_amt and signals.is_financial_context)
        or signals.has_escalation
        or signals.is_repeat_followup
        or clf.sub_category in p_rules.get("p3_sub_categories", ["service_or_billing_dispute"])
        or (clf.impact_level == "high" and clf.impact_conf >= imp_thresh and route == "human")
    ):
        priority = "P3"
    else:
        priority = "P2"

    r_ms = round((time.perf_counter() - t_route) * 1000, 2)
    tot_ms = round(
        regex_ms + clf.stage_classification_ms + clf.stage_urgent_ms + clf.stage_impact_ms + r_ms, 1
    )

    return TriageDecision(
        ticket_id=ticket.ticket_id,
        category=clf.category,
        sub_category=clf.sub_category,
        priority=priority,
        route=route,
        confidence=clf.confidence,
        reason="；".join(reasons),
        model=clf.model_name,
        urgent_level=clf.urgent_level,
        urgent_conf=clf.urgent_conf,
        impact_level=clf.impact_level,
        impact_conf=clf.impact_conf,
        regex_ms=regex_ms,
        stage_classification_ms=clf.stage_classification_ms,
        stage_urgent_ms=clf.stage_urgent_ms,
        stage_impact_ms=clf.stage_impact_ms,
        router_ms=r_ms,
        total_ms=tot_ms,
        signal_tags=tags,
        structured_state=state_str,
        model_traces=clf.model_traces,
    )
