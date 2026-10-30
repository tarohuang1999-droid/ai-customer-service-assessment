from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

CORE_COLUMNS = ["ticket_id", "created_at", "channel", "customer_name", "subject", "body"]

_BR_RE = re.compile(r"<\s*(br|/p|p)\s*/?\s*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class Ticket:
    ticket_id: str
    created_at: str
    channel: str
    customer_name: str
    subject: str
    body: str
    extra_empty_cols: int = 0
    had_html: bool = False


def strip_html(text: str) -> tuple[str, bool]:
    """<br>、<p> 轉成換行，其餘 HTML 標籤移除。回傳清理後文字與是否含標籤。"""
    if not _TAG_RE.search(text):
        return text, False
    return _TAG_RE.sub("", _BR_RE.sub("\n", text)).strip(), True


def load_tickets(csv_path: str | Path) -> list[Ticket]:
    """只讀前 6 欄（試算表匯出的空白欄忽略）、去除前後空白、移除 HTML 標籤。"""
    tickets: list[Ticket] = []
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader, [])[:6]]
        if header != CORE_COLUMNS:
            raise ValueError(f"Unexpected CSV header in {csv_path}: {header}")
        for row in reader:
            if not row or not row[0].strip():
                continue
            tid, created_at, channel, name, subject, body = [c.strip() for c in (row + [""] * 6)[:6]]
            body, had_html = strip_html(body)
            tickets.append(Ticket(tid, created_at, channel, name, subject, body,
                                  extra_empty_cols=max(0, len(row) - 6), had_html=had_html))
    return tickets


def build_model_input(ticket: Ticket, max_body_chars: int = 300) -> str:
    """模型輸入只有主旨與內文；過長內文保留開頭 65% 與結尾 35%。"""
    body = ticket.body
    if len(body) > max_body_chars:
        head = int(max_body_chars * 0.65)
        body = f"{body[:head]}...{body[-(max_body_chars - head):]}"
    return f"主旨：{ticket.subject}\n內文：{body}"
