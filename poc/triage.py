from __future__ import annotations

import argparse
import csv
from datetime import datetime
import functools
import http.server
import json
import shutil
import time
import tomllib
import webbrowser
from pathlib import Path

from evaluate import compute_eval_metrics, load_expected_labels, write_review_html
from pipeline.models import create_model
from pipeline.preprocess import load_tickets
from pipeline.router import TriageDecision, triage_one
from pipeline.signals import extract_signals


def load_toml(path: str | Path) -> dict:
    with Path(path).open("rb") as f:
        return tomllib.load(f)


def write_triage_csv(out_csv: str | Path, decisions: list[TriageDecision]) -> None:
    fieldnames = [
        "ticket_id",
        "category",
        "sub_category",
        "priority",
        "route",
        "confidence",
        "urgent_level",
        "impact_level",
        "total_ms",
        "reason",
        "model",
    ]
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
                    "urgent_level": f"{d.urgent_level}({d.urgent_conf:.2f})",
                    "impact_level": f"{d.impact_level}({d.impact_conf:.2f})",
                    "total_ms": f"{d.total_ms:.1f}",
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
) -> tuple[list[TriageDecision], dict | None, Path]:
    cfg_dir = Path(config_dir)
    out_root = Path(output_dir)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = out_root / "run" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "run.log"

    def log(msg: str, console: bool = True) -> None:
        if console:
            print(msg, flush=True)
        with log_path.open("a", encoding="utf-8") as lf:
            lf.write(msg + "\n")

    t_prep0 = time.perf_counter()
    labels_cfg = load_toml(cfg_dir / "labels.toml")
    regex_cfg = load_toml(cfg_dir / "regex_rules.toml")
    route_cfg = load_toml(cfg_dir / "route_rules.toml")

    anon_names = set(regex_cfg.get("anonymous_names", ["佚名", "test", "測試", ""]))
    tickets = load_tickets(input_csv, anonymous_names=anon_names)
    prep_ms = round((time.perf_counter() - t_prep0) * 1000, 2)

    model = create_model(model_name, endpoint=endpoint, api_key=api_key)
    log(
        f"[START] run_id={run_id} model={model.name} tickets={len(tickets)} "
        f"threshold={threshold:.2f} stage=preprocess:{prep_ms}ms"
    )

    decisions: list[TriageDecision] = []
    n_total = len(tickets)
    for idx, t in enumerate(tickets, 1):
        t_sig0 = time.perf_counter()
        sigs = extract_signals(t, regex_cfg)
        regex_ms = round((time.perf_counter() - t_sig0) * 1000, 2)

        dec = triage_one(t, sigs, regex_ms, model, labels_cfg, route_cfg, threshold_override=threshold)
        decisions.append(dec)
        log(
            f"[{idx:02d}/{n_total:02d}] {t.ticket_id} | "
            f"stage=regex:{dec.regex_ms:.1f}ms "
            f"stage=classification:{dec.stage_classification_ms:.0f}ms "
            f"stage=urgent_level:{dec.stage_urgent_ms:.0f}ms "
            f"stage=impact_level:{dec.stage_impact_ms:.0f}ms "
            f"stage=router:{dec.router_ms:.1f}ms | "
            f"total={dec.total_ms:.0f}ms -> {dec.category}/{dec.sub_category} "
            f"(route={dec.route}, prio={dec.priority}, conf={dec.confidence:.2f}, "
            f"urgent={dec.urgent_level}:{dec.urgent_conf:.2f}, impact={dec.impact_level}:{dec.impact_conf:.2f})"
        )
        log(f"  [INPUT_STATE] {json.dumps(dec.structured_state, ensure_ascii=False)}", console=False)
        for tr in dec.model_traces:
            q_names = list(tr["input"].get("questions", {}).keys())
            log(
                f"  [MODEL_IO] stage={tr['stage']} ms={tr['ms']} input_tokens={tr['input_tokens']} "
                f"questions={q_names} output={json.dumps(tr['output'], ensure_ascii=False)}",
                console=False,
            )

    write_triage_csv(run_dir / "triage_result.csv", decisions)

    eval_metrics = None
    if gold_csv and Path(gold_csv).exists():
        gold = load_expected_labels(gold_csv)
        eval_metrics = compute_eval_metrics(decisions, gold)
        write_review_html(run_dir / "review.html", tickets, decisions, gold, eval_metrics, prep_ms=prep_ms)

    total_run_ms = prep_ms + sum(d.total_ms for d in decisions)
    log(
        f"[DONE] total_time={total_run_ms / 1000:.2f}s avg={total_run_ms / n_total:.1f}ms/ticket "
        f"stage=classification_avg:{sum(d.stage_classification_ms for d in decisions) / n_total:.0f}ms "
        f"stage=urgent_level_avg:{sum(d.stage_urgent_ms for d in decisions) / n_total:.0f}ms "
        f"stage=impact_level_avg:{sum(d.stage_impact_ms for d in decisions) / n_total:.0f}ms"
    )

    for fname in ("triage_result.csv", "review.html", "run.log"):
        src = run_dir / fname
        if src.exists():
            shutil.copy2(src, out_root / fname)

    return decisions, eval_metrics, run_dir


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="T-Travel Ticket Triage PoC CLI")
    parser.add_argument("--input", default=str(base_dir / "data" / "sample_tickets.csv"), help="Input CSV path")
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

    decisions, metrics, run_dir = run_pipeline(
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
    print(f"[OK] Processed {len(decisions)} tickets -> {run_dir}")
    print(f"     route=human: {human_cnt} ({human_cnt / len(decisions) * 100:.1f}%) | route=auto: {len(decisions) - human_cnt}")
    if metrics:
        print(
            f"     Eval -> Category Acc: {metrics['cat_acc']}% | Sub-cat Acc: {metrics['sub_acc']}% | "
            f"Route Error: {metrics['route_err_rate']}% | False Auto: {metrics['false_auto']}"
        )

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
