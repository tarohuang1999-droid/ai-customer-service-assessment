from __future__ import annotations

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
    category_conf: float = 0.0
    sub_category_conf: float = 0.0
    is_urgent_prob: float = 0.0
    is_high_impact_prob: float = 0.0
    signal_tags: list[str] = field(default_factory=list)
    structured_state: str = ""


def triage_one(
    ticket: Ticket,
    signals: Signals,
    model: DecisionModel,
    labels_cfg: dict[str, Any],
    route_cfg: dict[str, Any],
    threshold_override: float | None = None,
) -> TriageDecision:
    state_str = build_structured_state(ticket, signals)
    tags = signals.active_tags()

    # 1. Pre-rules: Spam / Test
    if signals.is_spam or signals.is_test:
        kind = "系統測試單" if signals.is_test else "外部推銷/博弈廣告"
        return TriageDecision(
            ticket_id=ticket.ticket_id,
            category="other_non_cs",
            sub_category="spam_or_test",
            priority="P4",
            route="auto",
            confidence=1.0,
            reason=f"規則前置攔截：{kind}（直接標記歸檔）",
            model="rule-precheck",
            category_conf=1.0,
            sub_category_conf=1.0,
            signal_tags=tags,
            structured_state=state_str,
        )

    # 2. Pre-rules: Insufficient info (extremely short body)
    if signals.is_short_insufficient:
        return TriageDecision(
            ticket_id=ticket.ticket_id,
            category="unknown",
            sub_category="insufficient_info",
            priority="P3",
            route="auto",
            confidence=1.0,
            reason="規則前置攔截：內文過短且缺訂單與具體訴求（套用固定補件模板）",
            model="rule-precheck",
            category_conf=1.0,
            sub_category_conf=1.0,
            signal_tags=tags,
            structured_state=state_str,
        )

    # 3. Hierarchical Decision Model (Stage 1: Category + Urgency + Impact -> Stage 2: Sub-category)
    clf: ClassificationResult = model.classify(state_str, labels_cfg)
    if clf.error:
        return TriageDecision(
            ticket_id=ticket.ticket_id,
            category="unknown",
            sub_category="insufficient_info",
            priority="P2",
            route="human",
            confidence=0.0,
            reason=f"Fail-closed 模型異常轉人工：{clf.error}",
            model=clf.model_name,
            signal_tags=tags,
            structured_state=state_str,
        )

    sub_opts = labels_cfg["sub_categories"][clf.category]["options"]
    default_route = str(sub_opts[clf.sub_category]["route"])
    route = default_route
    reasons: list[str] = [
        f"分層模型({clf.model_name})：{clf.category}(p={clf.category_conf:.2f}) -> {clf.sub_category}(p={clf.sub_category_conf:.2f}, 預設={default_route})"
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
        reasons.append(f"信心門檻攔截：最低階層信心 {clf.confidence:.2f} < {conf_thresh:.2f}")

    # 6. Priority determination (Regex signals + Clef urgency/impact probabilities)
    p_rules = route_cfg.get("priority_rules", {})
    urg_thresh = float(route_cfg.get("urgency_prob_threshold", 0.70))
    imp_thresh = float(route_cfg.get("impact_prob_threshold", 0.70))

    if clf.category in p_rules.get("p4_categories", ["other_non_cs"]):
        priority = "P4"
    elif signals.is_urgent_72h or (clf.is_urgent_prob >= urg_thresh and route == "human"):
        priority = "P1"
        if not signals.is_urgent_72h:
            reasons.append(f"模型緊急度判定 P1 (urgent_p={clf.is_urgent_prob:.2f})")
    elif (
        (signals.max_amount > high_amt and signals.is_financial_context)
        or signals.has_escalation
        or signals.is_repeat_followup
        or clf.sub_category in p_rules.get("p2_sub_categories", ["service_or_billing_dispute"])
        or (clf.is_high_impact_prob >= imp_thresh and route == "human")
    ):
        priority = "P2"
    else:
        priority = "P3"

    return TriageDecision(
        ticket_id=ticket.ticket_id,
        category=clf.category,
        sub_category=clf.sub_category,
        priority=priority,
        route=route,
        confidence=clf.confidence,
        reason="；".join(reasons),
        model=clf.model_name,
        category_conf=clf.category_conf,
        sub_category_conf=clf.sub_category_conf,
        is_urgent_prob=clf.is_urgent_prob,
        is_high_impact_prob=clf.is_high_impact_prob,
        signal_tags=tags,
        structured_state=state_str,
    )
