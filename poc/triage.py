from __future__ import annotations

import argparse
import csv
import functools
import http.server
import json
import tomllib
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path

from evaluate import compute_eval_metrics, load_expected_labels, write_review_html
from pipeline.models import create_model
from pipeline.preprocess import load_tickets
from pipeline.router import TriageDecision, triage_one


def load_toml(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def write_triage_csv(path: Path, decisions: list[TriageDecision]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticket_id", "category", "sub_category", "route", "priority", "confidence",
                    "urgency", "impact", "reason", "model"])
        for d in decisions:
            w.writerow([d.ticket_id, d.category, d.sub_category, d.route, d.priority, f"{d.confidence:.4f}",
                        f"{d.urgency}({d.urgency_conf:.2f})", f"{d.impact}({d.impact_conf:.2f})", d.reason, d.model])


def run(input_csv: Path, output_dir: Path, config_dir: Path, model_name: str, endpoint: str | None,
        api_key: str | None, threshold: float, gold_csv: Path | None) -> Path:
    labels = load_toml(config_dir / "labels.toml")
    routing = load_toml(config_dir / "routing.toml")
    result_dir = output_dir / f"result-{datetime.now():%Y%m%d_%H%M%S}"
    result_dir.mkdir(parents=True, exist_ok=True)

    tickets = load_tickets(input_csv)
    model = create_model(model_name, endpoint=endpoint, api_key=api_key)
    with (result_dir / "run.log").open("w", encoding="utf-8") as log_f:
        def log(msg: str, console: bool = True) -> None:
            if console:
                print(msg, flush=True)
            log_f.write(msg + "\n")

        log(f"[START] model={model.name} tickets={len(tickets)} threshold={threshold:.2f}")
        decisions: list[TriageDecision] = []
        for i, t in enumerate(tickets, 1):
            d = triage_one(t, model, labels, routing, threshold)
            decisions.append(d)
            log(f"[{i:02d}/{len(tickets)}] {t.ticket_id} {d.total_ms:.0f}ms -> {d.category}/{d.sub_category} "
                f"route={d.route} prio={d.priority} urgency={d.urgency} impact={d.impact} | {d.reason}")
            log(f"  [INPUT] {json.dumps(d.model_input, ensure_ascii=False)}", console=False)
            for tr in d.model_traces:
                log(f"  [MODEL_IO] stage={tr['stage']} ms={tr['ms']} input_tokens={tr['input_tokens']} "
                    f"output={json.dumps(tr['output'], ensure_ascii=False)}", console=False)

        write_triage_csv(result_dir / "triage_result.csv", decisions)
        gold = load_expected_labels(gold_csv) if gold_csv and gold_csv.exists() else {}
        metrics = compute_eval_metrics(decisions, gold) if gold else None
        write_review_html(result_dir / "review.html", tickets, decisions, gold, metrics, model.name)

        routes = Counter(d.route for d in decisions)
        total_ms = sum(d.total_ms for d in decisions)
        log(f"[DONE] {total_ms / 1000:.1f}s, {total_ms / len(decisions):.0f}ms/ticket | "
            f"human={routes['human']} auto={routes['auto']}")
        if metrics:
            log(f"[EVAL] category={metrics['cat_acc']}% sub_category={metrics['sub_acc']}% route={metrics['route_acc']}% "
                f"priority={metrics['prio_acc']}% false_auto={metrics['false_auto']}")
    return result_dir


def main() -> None:
    base = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="T 旅遊工單分流 PoC")
    ap.add_argument("--input", default=str(base / "data" / "sample_tickets.csv"))
    ap.add_argument("--output-dir", default=str(base / "output"), help="每次執行建立 result-<時間> 子資料夾")
    ap.add_argument("--config-dir", default=str(base / "config"))
    ap.add_argument("--model", default="mock", choices=["llamacpp", "clef", "jev", "mock"],
                    help="llamacpp/clef：地端決策模型；jev：遠端 API（僅限虛構資料）；mock：離線基準")
    ap.add_argument("--endpoint", default=None, help="覆寫 /v1/systemone 端點")
    ap.add_argument("--api-key", default=None, help="Jev API token")
    ap.add_argument("--threshold", type=float, default=0.70, help="分類信心門檻")
    ap.add_argument("--eval", default=str(base / "data" / "expected_labels.csv"), help="標準標註 CSV")
    ap.add_argument("--serve", action="store_true", help="執行後以本機伺服器開啟 review.html")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()

    result_dir = run(Path(a.input), Path(a.output_dir), Path(a.config_dir), a.model, a.endpoint,
                     a.api_key, a.threshold, Path(a.eval))
    print(f"[OK] 輸出：{result_dir}")
    if a.serve:
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(result_dir))
        url = f"http://127.0.0.1:{a.port}/review.html"
        print(f"Serving {url} (Ctrl+C to stop)")
        webbrowser.open(url)
        with http.server.HTTPServer(("127.0.0.1", a.port), handler) as httpd:
            httpd.serve_forever()


if __name__ == "__main__":
    main()
