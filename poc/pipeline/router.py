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
    risk: float = 0.0
    queue_rank: int = 0
    model_input: str = ""
    model_traces: list[dict[str, Any]] = field(default_factory=list)
    total_ms: float = 0.0


def risk_score(confidence: float, urgency: str, urgency_conf: float, impact: str, impact_conf: float,
               w: dict[str, float]) -> float:
    """風險分數 = w_c×(1−分類信心) + w_u×急迫度選 high 的信心 + w_i×影響程度選 high 的信心。"""
    u = urgency_conf if urgency == "high" else 0.0
    i = impact_conf if impact == "high" else 0.0
    return w["w_c"] * (1 - confidence) + w["w_u"] * u + w["w_i"] * i


def triage_one(ticket: Ticket, model: DecisionModel, labels: dict[str, Any], routing: dict[str, Any]) -> TriageDecision:
    """決策模型回答 3 題 → 低信心歸 other/unclear → 依 mode 決定 route（rule：條件規則；risk：風險分數）。"""
    t0 = time.perf_counter()
    model_input = build_model_input(ticket, int(routing.get("max_body_chars", 300)))
    r = model.classify(model_input, labels)

    def done(**kw: Any) -> TriageDecision:
        return TriageDecision(ticket_id=ticket.ticket_id, created_at=ticket.created_at, model=r.model_name,
                              model_input=model_input, model_traces=r.model_traces,
                              total_ms=round((time.perf_counter() - t0) * 1000, 1), **kw)

    if r.error:  # fail-closed：模型異常一律轉人工，錯誤細節由 triage.py 寫入 log
        return done(category="other", sub_category="unclear", route="human", confidence=0.0,
                    urgency="low", urgency_conf=0.0, impact="low", impact_conf=0.0,
                    reason=f"模型異常轉人工：{r.error}")

    levels = dict(urgency=r.urgent_level, urgency_conf=r.urgent_conf, impact=r.impact_level, impact_conf=r.impact_conf)
    risk_cfg = routing["risk"]
    risk = risk_score(r.confidence, r.urgent_level, r.urgent_conf, r.impact_level, r.impact_conf, risk_cfg)

    # 1. 分類信心不足：系統判斷不了，歸 other/unclear
    cls_thr = float(routing.get("classification_threshold", 0.5))
    if r.confidence < cls_thr:
        return done(category="other", sub_category="unclear", route=routing["route"]["other/unclear"],
                    confidence=r.confidence, risk=risk, **levels,
                    reason=f"分類信心 {r.confidence:.2f} < {cls_thr:.2f}，歸為 other/unclear（模型原判 {r.category}/{r.sub_category}）")

    key = f"{r.category}/{r.sub_category}"
    mode = routing.get("mode", "rule")

    if mode == "rule":
        # 2. 條件規則：細項在 auto 清單內，且急迫度、影響程度都在允許清單內 -> auto；其餘 human
        cond = routing["rule"]["auto"].get(key)
        if cond is None:
            route, why = "human", f"{key} 不在 auto 清單"
        elif r.urgent_level not in cond["urgency"]:
            route, why = "human", f"急迫度 {r.urgent_level} 不在 auto 條件"
        elif r.impact_level not in cond["impact"]:
            route, why = "human", f"影響程度 {r.impact_level} 不在 auto 條件"
        else:
            route, why = "auto", "符合 auto 條件"
        return done(category=r.category, sub_category=r.sub_category, route=route, confidence=r.confidence,
                    risk=risk, reason=f"分類信心 {r.confidence:.2f}；{why}", **levels)

    # 2. 風險模式：細項對應 route；3. 風險分數 ≥ 門檻 -> human（只會從 auto 改成 human）
    route = routing["route"][key]
    reason = f"分類信心 {r.confidence:.2f}；風險 {risk:.2f}"
    if risk >= float(risk_cfg["threshold"]) and route == "auto":
        route = "human"
        reason += f" ≥ {float(risk_cfg['threshold']):.2f}，轉人工"

    return done(category=r.category, sub_category=r.sub_category, route=route, confidence=r.confidence,
                risk=risk, reason=reason, **levels)


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
