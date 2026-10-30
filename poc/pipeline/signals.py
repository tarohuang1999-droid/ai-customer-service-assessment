from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from .preprocess import Ticket

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_RELATIVE_DAYS = {"今天": 0, "今日": 0, "今晚": 0, "明天": 1, "明日": 1, "後天": 2}


@dataclass(slots=True)
class Signals:
    order_ids: list[str] = field(default_factory=list)
    max_amount: int = 0
    is_irrelevant: bool = False
    irrelevant_kind: str = ""
    is_urgent_72h: bool = False
    is_high_amount: bool = False
    has_escalation: bool = False
    is_repeat_followup: bool = False
    has_inline_pii: bool = False

    def tags(self) -> list[str]:
        out: list[str] = []
        if self.order_ids:
            out.append(f"order_id={','.join(self.order_ids)}")
        if self.max_amount:
            out.append(f"max_amount={self.max_amount}")
        for name in ("is_irrelevant", "is_urgent_72h", "is_high_amount", "has_escalation",
                     "is_repeat_followup", "has_inline_pii"):
            if getattr(self, name):
                out.append(name)
        return out


def _cn_number(token: str) -> int:
    """Parse a small Chinese or Arabic number such as 三, 十二, 2."""
    if token.isdigit():
        return int(token)
    if token.startswith("十"):
        token = "一" + token
    if "十" in token:
        tens, _, ones = token.partition("十")
        return _CN_DIGITS.get(tens, 1) * 10 + (_CN_DIGITS.get(ones, 0) if ones else 0)
    return _CN_DIGITS.get(token, 0)


def parse_amounts(text: str) -> list[int]:
    """Extract money amounts: 120,000 元 / 4.5 萬 / 三萬二 / 3 萬 2 千. Skips 萬粉, 萬人 等非金額用法."""
    amounts: list[int] = []
    for m in re.finditer(r"(\d{1,3}(?:,\d{3})+)(?!\d)", text):
        amounts.append(int(m.group(1).replace(",", "")))
    for m in re.finditer(r"(\d+)\s*元", text):
        amounts.append(int(m.group(1)))
    wan = r"([\d.]+|[一二兩三四五六七八九十]+)\s*萬\s*([\d]|[一二兩三四五六七八九])?\s*(千)?(?!\s*(粉|人|次|名|筆|點|位|個))"
    for m in re.finditer(wan, text):
        head = m.group(1)
        base = float(head) if re.fullmatch(r"[\d.]+", head) else _cn_number(head)
        value = base * 10000
        if m.group(2):
            value += _cn_number(m.group(2)) * 1000
        amounts.append(int(value))
    return amounts


def _parse_created(created_at: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(created_at.strip(), fmt)
        except ValueError:
            continue
    return None


def _date_mentions(text: str, created: date) -> list[tuple[int, date]]:
    """Return (position, date) for relative days and M/D or M月D日 mentions; dates without a year roll forward."""
    found: list[tuple[int, date]] = []
    for word, offset in _RELATIVE_DAYS.items():
        for m in re.finditer(word, text):
            found.append((m.start(), created + timedelta(days=offset)))
    for m in re.finditer(r"(?<![\d/])(\d{1,2})\s*(?:/|月)\s*(\d{1,2})\s*日?(?![\d/])", text):
        month, day = int(m.group(1)), int(m.group(2))
        try:
            d = date(created.year, month, day)
        except ValueError:
            continue
        if d < created - timedelta(days=1):
            try:
                d = date(created.year + 1, month, day)
            except ValueError:
                continue
        found.append((m.start(), d))
    return found


def _is_urgent(text: str, created_at: str, cfg: dict[str, Any], window_hours: int) -> bool:
    created = _parse_created(created_at)
    if not created:
        return False
    ctx_re = re.compile(cfg["patterns"]["departure_context"])
    win = int(cfg.get("context_window_chars", 15))
    for pos, d in _date_mentions(text, created.date()):
        delta_days = (d - created.date()).days
        if not (0 <= delta_days * 24 <= window_hours):
            continue
        if ctx_re.search(text[max(0, pos - win): pos + win]):
            return True
    return False


def extract_signals(ticket: Ticket, regex_cfg: dict[str, Any], route_cfg: dict[str, Any]) -> Signals:
    pats = regex_cfg["patterns"]
    text = f"{ticket.subject}\n{ticket.body}"

    irrelevant_kind = ""
    if re.search(pats["spam"], text):
        irrelevant_kind = "廣告"
    elif re.match(pats["test_ticket"], ticket.body.strip()):
        irrelevant_kind = "測試單"
    elif re.search(pats["auto_reply"], text):
        irrelevant_kind = "自動回覆"

    amounts = parse_amounts(text)
    max_amount = max(amounts) if amounts else 0
    threshold = int(route_cfg.get("high_amount_threshold", 30000))
    is_high_amount = max_amount > threshold and bool(re.search(pats["financial_context"], text))

    has_escalation = bool(re.search(pats["escalation"], text)) and not re.search(
        pats["media_interview_exclude"], text
    )

    return Signals(
        order_ids=re.findall(pats["order_id"], text),
        max_amount=max_amount,
        is_irrelevant=bool(irrelevant_kind),
        irrelevant_kind=irrelevant_kind,
        is_urgent_72h=_is_urgent(text, ticket.created_at, regex_cfg, int(route_cfg.get("urgent_window_hours", 72))),
        is_high_amount=is_high_amount,
        has_escalation=has_escalation,
        is_repeat_followup=ticket.is_repeat_customer or bool(re.search(pats["repeat_cue"], text)),
        has_inline_pii=bool(re.search(pats["inline_pii"], ticket.body)),
    )


def build_model_input(ticket: Ticket, max_body_chars: int = 300) -> str:
    """Subject + body; long bodies keep the first 65% and last 35% of the character budget."""
    body = ticket.body
    if len(body) > max_body_chars:
        head = int(max_body_chars * 0.65)
        body = f"{body[:head]}...{body[-(max_body_chars - head):]}"
    return f"主旨：{ticket.subject}\n內文：{body}"
