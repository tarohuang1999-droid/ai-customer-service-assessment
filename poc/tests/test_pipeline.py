from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.models import ClassificationResult, JevAPIClient, LlamaCppClient, MockDecisionModel
from pipeline.preprocess import Ticket, load_tickets, normalize_text
from pipeline.router import triage_one
from pipeline.signals import build_structured_state, extract_signals
from triage import load_toml, run_pipeline


class LowConfidenceStubModel:
    name = "low-conf-stub"

    def classify(self, state_str: str, labels_cfg: dict) -> ClassificationResult:
        return ClassificationResult(
            category="product_inquiry",
            sub_category="product_spec_and_price",
            category_conf=0.85,
            sub_category_conf=0.55,
            confidence=0.55,
            is_urgent_prob=0.10,
            is_high_impact_prob=0.10,
            model_name=self.name,
        )


class TestTicketTriagePipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.poc_dir = Path(__file__).resolve().parent.parent
        cls.cfg_dir = cls.poc_dir / "config"
        cls.labels_cfg = load_toml(cls.cfg_dir / "labels.toml")
        cls.regex_cfg = load_toml(cls.cfg_dir / "regex_rules.toml")
        cls.route_cfg = load_toml(cls.cfg_dir / "route_rules.toml")

    def test_normalize_fullwidth_and_spaces(self) -> None:
        norm, had_fw = normalize_text("  想改期到４月  ３月２８日出發  ")
        self.assertTrue(had_fw)
        self.assertEqual(norm, "想改期到4月 3月28日出發")

    def test_load_tickets_strips_trailing_empty_cols_and_tracks_repeat(self) -> None:
        sample_csv = self.poc_dir.parent / "sample_tickets.csv"
        tickets = load_tickets(sample_csv)
        self.assertEqual(len(tickets), 48)
        self.assertEqual(tickets[0].extra_empty_cols, 20)

        t1013 = next(t for t in tickets if t.ticket_id == "TK-1013")
        t1031 = next(t for t in tickets if t.ticket_id == "TK-1031")
        self.assertFalse(t1013.is_repeat_customer)
        self.assertTrue(t1031.is_repeat_customer)
        self.assertEqual(t1031.prior_ticket_ids, ["TK-1013"])

    def test_signals_and_structured_state(self) -> None:
        t = Ticket(
            ticket_id="TK-9001",
            created_at="2026-06-23 11:32",
            channel="email",
            customer_name="劉建宏",
            subject_raw="蜜月退費",
            body_raw="訂單 LT20260611567 總額 186,000 元申請全額退費",
            subject="蜜月退費",
            body="訂單 LT20260611567 總額 186,000 元申請全額退費",
        )
        sigs = extract_signals(t, self.regex_cfg)
        self.assertEqual(sigs.order_ids, ["LT20260611567"])
        self.assertEqual(sigs.max_amount, 186000)
        self.assertTrue(sigs.is_financial_context)
        state = build_structured_state(t, sigs)
        self.assertIn("ticket_id: TK-9001", state)
        self.assertIn("max_amount=186000", state)

    def test_low_confidence_forces_human_route(self) -> None:
        t = Ticket(
            ticket_id="TK-9002",
            created_at="2026-06-22 10:00",
            channel="email",
            customer_name="王小明",
            subject_raw="詢問行程",
            body_raw="請問東京五日遊費用包含導遊小費嗎？",
            subject="詢問行程",
            body="請問東京五日遊費用包含導遊小費嗎？",
        )
        sigs = extract_signals(t, self.regex_cfg)
        dec = triage_one(t, sigs, LowConfidenceStubModel(), self.labels_cfg, self.route_cfg, threshold_override=0.70)
        self.assertEqual(dec.route, "human")
        self.assertIn("信心門檻攔截", dec.reason)

    def test_hard_rule_overrides_auto_subcategory_to_human(self) -> None:
        # TK-1042 is document_reissue_and_invoice (default auto), but urgent ("明天要用") -> must be human & P1
        t = Ticket(
            ticket_id="TK-1042",
            created_at="2026-06-26 13:15",
            channel="email",
            customer_name="康家豪",
            subject_raw="沒收到電子票券 QR code，明天要用！",
            body_raw="明天要去六福村使用的門票，訂單顯示已付款成功但一直沒收到 QR code，請今天處理。",
            subject="沒收到電子票券 QR code，明天要用！",
            body="明天要去六福村使用的門票，訂單顯示已付款成功但一直沒收到 QR code，請今天處理。",
        )
        sigs = extract_signals(t, self.regex_cfg)
        dec = triage_one(t, sigs, MockDecisionModel(), self.labels_cfg, self.route_cfg)
        self.assertEqual(dec.sub_category, "document_reissue_and_invoice")
        self.assertEqual(dec.route, "human")
        self.assertEqual(dec.priority, "P1")

    def test_unreachable_endpoints_fail_closed_to_human(self) -> None:
        t = Ticket(
            ticket_id="TK-9003",
            created_at="2026-06-22 10:00",
            channel="email",
            customer_name="測試員",
            subject_raw="東京五日遊費用",
            body_raw="請問東京經典五日遊售價是否包含機場稅與小費？",
            subject="東京五日遊費用",
            body="請問東京經典五日遊售價是否包含機場稅與小費？",
        )
        sigs = extract_signals(t, self.regex_cfg)
        llama_client = LlamaCppClient(endpoint="http://127.0.0.1:9/v1/systemone", timeout=0.2)
        jev_client = JevAPIClient(endpoint="http://127.0.0.1:9/v1/systemone", api_key="test-key", timeout=0.2)

        for client in (llama_client, jev_client):
            dec = triage_one(t, sigs, client, self.labels_cfg, self.route_cfg)
            self.assertEqual(dec.route, "human")
            self.assertIn("Fail-closed 模型異常轉人工", dec.reason)

    def test_end_to_end_pipeline_outputs_48_rows_and_zero_false_auto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            decisions, metrics = run_pipeline(
                input_csv=self.poc_dir.parent / "sample_tickets.csv",
                output_dir=tmp_dir,
                config_dir=self.cfg_dir,
                model_name="mock",
                threshold=0.70,
                gold_csv=self.poc_dir / "data" / "expected_labels.csv",
            )
            self.assertEqual(len(decisions), 48)
            self.assertIsNotNone(metrics)
            self.assertEqual(metrics["false_auto"], 0)
            self.assertTrue((Path(tmp_dir) / "triage_result.csv").exists())
            self.assertTrue((Path(tmp_dir) / "summary.md").exists())
            self.assertTrue((Path(tmp_dir) / "eval_report.md").exists())
            self.assertTrue((Path(tmp_dir) / "review.html").exists())


if __name__ == "__main__":
    unittest.main()
