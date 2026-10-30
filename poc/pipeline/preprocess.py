from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


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
    had_fullwidth_alnum: bool = False
    is_repeat_customer: bool = False
    prior_ticket_ids: list[str] = field(default_factory=list)


_FULLWIDTH_ALNUM_RE = re.compile(r"[\uff10-\uff19\uff21-\uff3a\uff41-\uff5a]")


def normalize_text(text: str) -> tuple[str, bool]:
    had_fw = bool(_FULLWIDTH_ALNUM_RE.search(text))
    norm = unicodedata.normalize("NFKC", text)
    norm = re.sub(r"[ \t]+", " ", norm).strip()
    return norm, had_fw


def load_tickets(csv_path: str | Path, anonymous_names: set[str] | None = None) -> list[Ticket]:
    anon = anonymous_names or {"佚名", "test", "測試", ""}
    tickets: list[Ticket] = []
    seen_by_customer: dict[str, list[str]] = {}

    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header or len(header) < 6:
            raise ValueError(f"Invalid CSV header in {csv_path}")

        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            core = [cell.strip() for cell in (row[:6] + [""] * 6)[:6]]
            extra_cols = len(row) - 6 if len(row) > 6 else 0
            tid, created_at, channel, cust_name, subj_raw, body_raw = core
            if not tid:
                continue

            subj, fw_s = normalize_text(subj_raw)
            body, fw_b = normalize_text(body_raw)

            prior_ids = list(seen_by_customer.get(cust_name, [])) if cust_name not in anon else []
            is_repeat = len(prior_ids) > 0
            if cust_name not in anon:
                seen_by_customer.setdefault(cust_name, []).append(tid)

            tickets.append(
                Ticket(
                    ticket_id=tid,
                    created_at=created_at,
                    channel=channel,
                    customer_name=cust_name,
                    subject_raw=subj_raw,
                    body_raw=body_raw,
                    subject=subj,
                    body=body,
                    extra_empty_cols=extra_cols,
                    had_fullwidth_alnum=(fw_s or fw_b),
                    is_repeat_customer=is_repeat,
                    prior_ticket_ids=prior_ids,
                )
            )
    return tickets
