from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .preprocess import Ticket


@dataclass(slots=True)
class Signals:
    order_ids: list[str] = field(default_factory=list)
    amounts: list[int] = field(default_factory=list)
    max_amount: int = 0
    is_financial_context: bool = False
    is_spam: bool = False
    is_test: bool = False
    is_short_insufficient: bool = False
    is_urgent_72h: bool = False
    has_escalation: bool = False
    is_repeat_followup: bool = False
    has_external_policy_change: bool = False
    has_inline_pii: bool = False

    def active_tags(self) -> list[str]:
        tags: list[str] = []
        if self.order_ids:
            tags.append(f"order_id={','.join(self.order_ids)}")
        if self.max_amount > 0:
            tags.append(f"max_amount={self.max_amount}")
        if self.is_spam:
            tags.append("spam")
        if self.is_test:
            tags.append("test_ticket")
        if self.is_short_insufficient:
            tags.append("short_insufficient")
        if self.is_urgent_72h:
            tags.append("urgent_72h")
        if self.has_escalation:
            tags.append("escalation")
        if self.is_repeat_followup:
            tags.append("repeat_followup")
        if self.has_external_policy_change:
            tags.append("external_policy_change")
        if self.has_inline_pii:
            tags.append("inline_pii")
        return tags


def extract_signals(ticket: Ticket, regex_cfg: dict[str, Any]) -> Signals:
    pats = regex_cfg["patterns"]
    min_chars = int(regex_cfg.get("min_body_chars", 6))
    text = f"{ticket.subject}\n{ticket.body}"

    order_ids = re.findall(pats["order_id"], text)

    amounts: list[int] = []
    for m in re.findall(pats["amount_yuan"], text):
        val = int(m.replace(",", ""))
        amounts.append(val)
    for m in re.findall(pats["amount_wan"], text):
        # Avoid matching follower counts like "8.7 萬粉"
        if not re.search(rf"{re.escape(m)}\s*萬\s*粉", text):
            amounts.append(int(float(m) * 10000))
    for m in re.findall(pats["amount_comma"], text):
        val = int(m.replace(",", ""))
        if val not in amounts:
            amounts.append(val)

    is_fin = bool(re.search(pats["financial_context"], text))
    is_spam = bool(re.search(pats["spam"], text))
    is_test = bool(re.match(pats["test_ticket"], ticket.subject) and re.match(pats["test_ticket"], ticket.body))

    # Very short body without clear complaint ("電話") or test
    is_short = (
        len(ticket.body) <= min_chars
        and not is_test
        and "電話" not in text
    )

    is_urgent = bool(re.search(pats["urgent_72h"], text))
    is_media_interview = bool(re.search(pats["media_interview_exclude"], text))
    has_escalation = bool(re.search(pats["escalation"], text)) and not is_media_interview
    is_repeat = ticket.is_repeat_customer or bool(re.search(pats["repeat_cue"], text))
    has_ext_policy = bool(re.search(pats["external_policy_change"], text))
    has_pii = bool(re.search(pats["inline_pii"], ticket.body))

    return Signals(
        order_ids=order_ids,
        amounts=amounts,
        max_amount=max(amounts) if amounts else 0,
        is_financial_context=is_fin,
        is_spam=is_spam,
        is_test=is_test,
        is_short_insufficient=is_short,
        is_urgent_72h=is_urgent,
        has_escalation=has_escalation,
        is_repeat_followup=is_repeat,
        has_external_policy_change=has_ext_policy,
        has_inline_pii=has_pii,
    )


def build_structured_state(ticket: Ticket, signals: Signals, max_body_chars: int = 300) -> str:
    body = ticket.body
    if len(body) > max_body_chars:
        head_n = int(max_body_chars * 0.65)
        tail_n = max_body_chars - head_n
        body = f"{body[:head_n]}...{body[-tail_n:]}"
    return f"主旨：{ticket.subject}\n內文：{body}"
