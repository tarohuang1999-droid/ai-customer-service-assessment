from __future__ import annotations

import argparse
import csv
import functools
import http.server
import tomllib
import webbrowser
from pathlib import Path

from evaluate import compute_eval_metrics, load_expected_labels, write_eval_report_md, write_review_html, write_summary_md
from pipeline.models import create_model
from pipeline.preprocess import load_tickets
from pipeline.router import TriageDecision, triage_one
from pipeline.signals import extract_signals


def load_toml(path: str | Path) -> dict:
    with Path(path).open("rb") as f:
        return tomllib.load(f)


def write_triage_csv(out_csv: str | Path, decisions: list[TriageDecision]) -> None:
    fieldnames = ["ticket_id", "category", "sub_category", "priority", "route", "confidence", "reason", "model"]
    with Path(out_csv).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in decisions:
            writer.writerow(
                {
                    "ticket_id": d.ticket_id,
                    "category": d.category,
                    "sub_category": d.sub_category,
                    "priority": d.priority,
                    "route": d.route,
                    "confidence": f"{d.confidence:.4f}",
                    "reason": d.reason,
                    "model": d.model,
                }
            )


def run_pipeline(
    input_csv: str | Path,
    output_dir: str | Path,
    config_dir: str | Path,
    model_name: str = "llamacpp",
    endpoint: str | None = None,
    api_key: str | None = None,
    threshold: float = 0.70,
    gold_csv: str | Path | None = None,
) -> tuple[list[TriageDecision], dict | None]:
    cfg_dir = Path(config_dir)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    labels_cfg = load_toml(cfg_dir / "labels.toml")
    regex_cfg = load_toml(cfg_dir / "regex_rules.toml")
    route_cfg = load_toml(cfg_dir / "route_rules.toml")

    anon_names = set(regex_cfg.get("anonymous_names", ["佚名", "test", "測試", ""]))
    tickets = load_tickets(input_csv, anonymous_names=anon_names)
    model = create_model(model_name, endpoint=endpoint, api_key=api_key)

    decisions: list[TriageDecision] = []
    for t in tickets:
        sigs = extract_signals(t, regex_cfg)
        dec = triage_one(t, sigs, model, labels_cfg, route_cfg, threshold_override=threshold)
        decisions.append(dec)

    write_triage_csv(out_dir / "triage_result.csv", decisions)

    eval_metrics = None
    if gold_csv and Path(gold_csv).exists():
        gold = load_expected_labels(gold_csv)
        eval_metrics = compute_eval_metrics(decisions, gold)
        write_eval_report_md(out_dir / "eval_report.md", eval_metrics)
        write_review_html(out_dir / "review.html", tickets, decisions, gold, eval_metrics)

    write_summary_md(out_dir / "summary.md", tickets, decisions, eval_metrics)
    return decisions, eval_metrics


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="T-Travel Ticket Triage PoC CLI")
    parser.add_argument("--input", default=str(base_dir.parent / "sample_tickets.csv"), help="Input CSV path")
    parser.add_argument("--output-dir", default=str(base_dir / "output"), help="Output directory")
    parser.add_argument("--config-dir", default=str(base_dir / "config"), help="Config directory")
    parser.add_argument("--model", default="mock", choices=["llamacpp", "clef", "jev", "mock"], help="Decision model backend")
    parser.add_argument("--endpoint", default=None, help="Override /v1/systemone endpoint URL")
    parser.add_argument("--api-key", default=None, help="Jev API Bearer token")
    parser.add_argument("--threshold", type=float, default=0.70, help="Confidence threshold (default: 0.70)")
    parser.add_argument("--eval", default=str(base_dir / "data" / "expected_labels.csv"), help="Golden set CSV for evaluation")
    parser.add_argument("--serve", action="store_true", help="Start local HTTP server to view review.html")
    parser.add_argument("--port", type=int, default=8000, help="Port for --serve (default: 8000)")
    args = parser.parse_args()

    decisions, metrics = run_pipeline(
        input_csv=args.input,
        output_dir=args.output_dir,
        config_dir=args.config_dir,
        model_name=args.model,
        endpoint=args.endpoint,
        api_key=args.api_key,
        threshold=args.threshold,
        gold_csv=args.eval,
    )

    human_cnt = sum(1 for d in decisions if d.route == "human")
    print(f"[OK] Processed {len(decisions)} tickets with model='{decisions[0].model if decisions else args.model}'")
    print(f"     route=human: {human_cnt} ({human_cnt / len(decisions) * 100:.1f}%) | route=auto: {len(decisions) - human_cnt}")
    if metrics:
        print(
            f"     Eval -> Category Acc: {metrics['cat_acc']}% | Sub-cat Acc: {metrics['sub_acc']}% | "
            f"Route Error: {metrics['route_err_rate']}% | False Auto: {metrics['false_auto']}"
        )
    print(f"     Outputs written to: {args.output_dir}/ (triage_result.csv, summary.md, eval_report.md, review.html)")

    if args.serve:
        out_path = Path(args.output_dir).resolve()
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out_path))
        url = f"http://127.0.0.1:{args.port}/review.html"
        print(f"Serving review UI at {url} (Ctrl+C to stop)")
        webbrowser.open(url)
        with http.server.HTTPServer(("127.0.0.1", args.port), handler) as httpd:
            httpd.serve_forever()


if __name__ == "__main__":
    main()
