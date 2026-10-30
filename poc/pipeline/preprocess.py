from __future__ import annotations

import csv
import html
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

CORE_COLUMNS = ["ticket_id", "created_at", "channel", "customer_name", "subject", "body"]

_FULLWIDTH_RE = re.compile(r"[０-９Ａ-Ｚａ-ｚ]")
_BR_RE = re.compile(r"<\s*(br|/p|p)\s*/?\s*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_SIGNATURE_RE = re.compile(r"^\s*(--\s*)?(從我的\s*\S+\s*傳送|寄自我的\s*\S+|Sent from my .+)\s*$", re.I | re.M)
_INDENT_RE = re.compile(r"^[ \t　]+", re.M)


@dataclass(slots=True)
class Ticket:
    ticket_id: str
    created_at: str
    channel: str
    customer_name: str
    subject: str
    body: str
    body_raw: str
    extra_empty_cols: int = 0
    cleaning: list[str] = field(default_factory=list)


def clean_text(text: str) -> tuple[str, list[str]]:
    """NFKC, strip HTML tags/entities, indentation and mobile signatures. Returns text and the steps applied."""
    steps: list[str] = []
    if _FULLWIDTH_RE.search(text):
        steps.append("fullwidth")
    text = unicodedata.normalize("NFKC", text)
    if _TAG_RE.search(text):
        steps.append("html_tag")
        text = _TAG_RE.sub("", _BR_RE.sub("\n", text))
    if html.unescape(text) != text:
        steps.append("html_entity")
        text = html.unescape(text)
    if _SIGNATURE_RE.search(text):
        steps.append("signature")
        text = _SIGNATURE_RE.sub("", text)
    if _INDENT_RE.search(text):
        steps.append("indent")
        text = _INDENT_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return text, steps


def load_tickets(csv_path: str | Path) -> list[Ticket]:
    """Read the 6 core columns (extra empty columns from the spreadsheet export are ignored) and clean text."""
    tickets: list[Ticket] = []
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader, [])[:6]]
        if header != CORE_COLUMNS:
            raise ValueError(f"Unexpected CSV header in {csv_path}: {header}")
        for row in reader:
            if not row or not row[0].strip():
                continue
            tid, created_at, channel, name, subj_raw, body_raw = [c.strip() for c in (row + [""] * 6)[:6]]
            subject, s1 = clean_text(subj_raw)
            body, s2 = clean_text(body_raw)
            tickets.append(Ticket(
                ticket_id=tid, created_at=created_at, channel=channel, customer_name=name,
                subject=subject, body=body, body_raw=body_raw,
                extra_empty_cols=max(0, len(row) - 6), cleaning=sorted(set(s1 + s2)),
            ))
    return tickets


def build_model_input(ticket: Ticket, max_body_chars: int = 300) -> str:
    """進件時間 + 主旨 + 內文。進件時間讓模型能判斷「72 小時內」；過長內文保留開頭 65% 與結尾 35%。"""
    body = ticket.body
    if len(body) > max_body_chars:
        head = int(max_body_chars * 0.65)
        body = f"{body[:head]}...{body[-(max_body_chars - head):]}"
    return f"進件時間：{ticket.created_at}\n主旨：{ticket.subject}\n內文：{body}"
