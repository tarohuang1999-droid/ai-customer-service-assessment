from __future__ import annotations

import csv
import html
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

CORE_COLUMNS = ["ticket_id", "created_at", "channel", "customer_name", "subject", "body"]


@dataclass(slots=True)
class Ticket:
    ticket_id: str
    created_at: str
    channel: str
    customer_name: str
    subject_raw: str
    body_raw: str
    subject: str
    body: str
    extra_empty_cols: int = 0
    cleaning_flags: list[str] = field(default_factory=list)
    is_repeat_customer: bool = False
    prior_ticket_ids: list[str] = field(default_factory=list)


_FULLWIDTH_RE = re.compile(r"[０-９Ａ-Ｚａ-ｚ]")
_BR_RE = re.compile(r"<\s*(br|/p|p)\s*/?\s*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_SIGNATURE_RE = re.compile(
    r"^\s*(--\s*)?(從我的\s*\S+\s*傳送|Sent from my .+|寄自我的\s*\S+)\s*$", re.I | re.M
)
_QUOTE_LINE_RE = re.compile(r"^\s*>.*$", re.M)
_ORIGINAL_MSG_RE = re.compile(r"(-{3,}\s*(Original Message|原始郵件|轉寄郵件)\s*-{3,}).*", re.I | re.S)


def clean_text(text: str) -> tuple[str, list[str]]:
    """Normalize one field and return the cleaned text plus the cleaning steps applied."""
    flags: list[str] = []
    if _FULLWIDTH_RE.search(text):
        flags.append("fullwidth")
    text = unicodedata.normalize("NFKC", text)

    if _BR_RE.search(text) or _TAG_RE.search(text):
        flags.append("html_tag")
        text = _BR_RE.sub("\n", text)
        text = _TAG_RE.sub("", text)
    unescaped = html.unescape(text)
    if unescaped != text:
        flags.append("html_entity")
        text = unescaped

    if _ORIGINAL_MSG_RE.search(text):
        flags.append("quoted_original")
        text = _ORIGINAL_MSG_RE.sub("", text)
    if _QUOTE_LINE_RE.search(text):
        flags.append("quoted_line")
        text = _QUOTE_LINE_RE.sub("", text)
    if _SIGNATURE_RE.search(text):
        flags.append("signature")
        text = _SIGNATURE_RE.sub("", text)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text, flags


def load_tickets(csv_path: str | Path, anonymous_names: set[str] | None = None) -> list[Ticket]:
    """Read the CSV, keep the 6 core columns, clean text and mark repeat senders."""
    anon = anonymous_names or {""}
    tickets: list[Ticket] = []
    seen_by_customer: dict[str, list[str]] = {}

    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header or [h.strip() for h in header[:6]] != CORE_COLUMNS:
            raise ValueError(f"Unexpected CSV header in {csv_path}: {header[:6] if header else header}")

        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            core = [cell.strip() for cell in (row + [""] * 6)[:6]]
            tid, created_at, channel, name, subj_raw, body_raw = core
            if not tid:
                continue
            extra = sum(1 for _ in row[6:])

            subject, f_s = clean_text(subj_raw)
            body, f_b = clean_text(body_raw)

            prior = list(seen_by_customer.get(name, [])) if name not in anon else []
            if name not in anon:
                seen_by_customer.setdefault(name, []).append(tid)

            tickets.append(
                Ticket(
                    ticket_id=tid,
                    created_at=created_at,
                    channel=channel,
                    customer_name=name,
                    subject_raw=subj_raw,
                    body_raw=body_raw,
                    subject=subject,
                    body=body,
                    extra_empty_cols=extra,
                    cleaning_flags=sorted(set(f_s + f_b)),
                    is_repeat_customer=bool(prior),
                    prior_ticket_ids=prior,
                )
            )
    return tickets
