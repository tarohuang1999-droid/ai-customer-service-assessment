from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class ClassificationResult:
    category: str
    sub_category: str
    confidence: float
    urgent_level: str
    urgent_conf: float
    impact_level: str
    impact_conf: float
    model_name: str
    stage_classification_ms: float = 0.0
    stage_urgent_ms: float = 0.0
    stage_impact_ms: float = 0.0
    classification_probs: dict[str, float] = field(default_factory=dict)
    urgent_probs: dict[str, float] = field(default_factory=dict)
    impact_probs: dict[str, float] = field(default_factory=dict)
    model_traces: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class DecisionModel(Protocol):
    name: str

    def classify(self, state_str: str, labels_cfg: dict[str, Any]) -> ClassificationResult: ...


class _SystemOneHTTPBase:
    """Decision-model client for /v1/systemone (local llama.cpp + Clef, or remote Jev).

    Each ticket is asked 3 independent choice questions:
      1. classification: "<category>/<sub_category>" (18 options)
      2. urgency_level:  high / medium / low
      3. impact_level:   high / medium / low
    The model returns a probability per option and a confidence; it generates no text.
    """

    def __init__(self, name: str, endpoint: str, headers: dict[str, str], timeout: float = 30.0,
                 retries: int = 1) -> None:
        self.name = name
        self.endpoint = endpoint
        self.headers = headers
        self.timeout = timeout
        self.retries = retries  # 失敗時重試次數

    def _post_systemone(
        self,
        stage_name: str,
        state_str: str,
        questions: dict[str, Any],
        traces: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {"state": state_str, "questions": questions}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        attempts = self.retries + 1
        last_err: Exception | None = None
        for attempt in range(1, attempts + 1):
            req = urllib.request.Request(self.endpoint, data=body, headers=self.headers, method="POST")
            t0 = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                data["answers"][stage_name]["choice"]  # 檢查輸出格式
            except urllib.error.HTTPError as e:
                last_err = RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}")
                continue
            except Exception as e:  # 逾時、連線失敗、輸出格式錯誤
                last_err = e
                continue
            traces.append({
                "stage": stage_name,
                "ms": round((time.perf_counter() - t0) * 1000, 1),
                "attempt": attempt,
                "input_tokens": data.get("usage", {}).get("input_tokens"),
                "input": payload,
                "output": data.get("answers", {}),
            })
            return data
        raise RuntimeError(f"stage={stage_name} attempts={attempts} {type(last_err).__name__}: {last_err}")

    def classify(self, state_str: str, labels_cfg: dict[str, Any]) -> ClassificationResult:
        t0 = time.perf_counter()
        traces: list[dict[str, Any]] = []
        try:
            # Q1: classification
            t_c0 = time.perf_counter()
            clf_cfg = labels_cfg["classification"]
            merged_criteria = {
                pair_key: opt_val["description"]
                for pair_key, opt_val in clf_cfg["options"].items()
            }
            q_clf = {
                "classification": {
                    "type": "choice",
                    "instructions": clf_cfg["instructions"],
                    "criteria": merged_criteria,
                }
            }
            r1 = self._post_systemone("classification", state_str, q_clf, traces)
            stage_clf_ms = round((time.perf_counter() - t_c0) * 1000, 1)

            ans1 = r1["answers"]["classification"]
            chosen_pair = str(ans1["choice"])
            category, sub_cat = chosen_pair.split("/", 1)
            clf_probs = {k: round(float(v), 4) for k, v in ans1.get("probabilities", {}).items()}
            clf_conf = float(ans1.get("confidence", clf_probs.get(chosen_pair, 0.0)))

            # Q2: urgency_level
            t_u0 = time.perf_counter()
            urg_cfg = labels_cfg["urgency_level"]
            q_urg = {
                "urgency_level": {
                    "type": "choice",
                    "instructions": urg_cfg["instructions"],
                    "criteria": {k: v["description"] for k, v in urg_cfg["options"].items()},
                }
            }
            r2 = self._post_systemone("urgency_level", state_str, q_urg, traces)
            stage_urg_ms = round((time.perf_counter() - t_u0) * 1000, 1)
            ans2 = r2["answers"]["urgency_level"]
            urgent_level = str(ans2["choice"])
            urgent_probs = {k: round(float(v), 4) for k, v in ans2.get("probabilities", {}).items()}
            urgent_conf = float(ans2.get("confidence", urgent_probs.get(urgent_level, 0.0)))

            # Q3: impact_level
            t_i0 = time.perf_counter()
            imp_cfg = labels_cfg["impact_level"]
            q_imp = {
                "impact_level": {
                    "type": "choice",
                    "instructions": imp_cfg["instructions"],
                    "criteria": {k: v["description"] for k, v in imp_cfg["options"].items()},
                }
            }
            r3 = self._post_systemone("impact_level", state_str, q_imp, traces)
            stage_imp_ms = round((time.perf_counter() - t_i0) * 1000, 1)
            ans3 = r3["answers"]["impact_level"]
            impact_level = str(ans3["choice"])
            impact_probs = {k: round(float(v), 4) for k, v in ans3.get("probabilities", {}).items()}
            impact_conf = float(ans3.get("confidence", impact_probs.get(impact_level, 0.0)))

            return ClassificationResult(
                category=category,
                sub_category=sub_cat,
                confidence=round(clf_conf, 4),
                urgent_level=urgent_level,
                urgent_conf=round(urgent_conf, 4),
                impact_level=impact_level,
                impact_conf=round(impact_conf, 4),
                model_name=self.name,
                stage_classification_ms=stage_clf_ms,
                stage_urgent_ms=stage_urg_ms,
                stage_impact_ms=stage_imp_ms,
                classification_probs=clf_probs,
                urgent_probs=urgent_probs,
                impact_probs=impact_probs,
                model_traces=traces,
            )
        except Exception as exc:
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            return ClassificationResult(
                category="other",
                sub_category="unclear",
                confidence=0.0,
                urgent_level="low",
                urgent_conf=0.0,
                impact_level="low",
                impact_conf=0.0,
                model_name=self.name,
                stage_classification_ms=elapsed,
                model_traces=traces,
                error=str(exc) if isinstance(exc, RuntimeError) else f"{type(exc).__name__}: {exc}",
            )


class LlamaCppClient(_SystemOneHTTPBase):
    """Local llama.cpp server client for Clef GGUF (/v1/systemone)."""

    def __init__(self, endpoint: str | None = None, timeout: float = 30.0) -> None:
        url = endpoint or os.environ.get("LLAMACPP_URL", "http://localhost:8090/v1/systemone")
        super().__init__(
            name="llamacpp-clef",
            endpoint=url,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )


class JevAPIClient(_SystemOneHTTPBase):
    """Remote Jev decision-model API (/v1/systemone).

    Sends ticket text to an external service: use with synthetic data only until
    legal approves the vendor (see answers.md Q3-6).
    """

    def __init__(self, endpoint: str | None = None, api_key: str | None = None, timeout: float = 30.0) -> None:
        url = endpoint or os.environ.get("JEV_API_URL", "https://api.jev.ai/v1/systemone")
        key = api_key or os.environ.get("JEV_API_KEY", "")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        super().__init__(name="jev-api", endpoint=url, headers=headers, timeout=timeout)


def create_model(model_type: str, endpoint: str | None = None, api_key: str | None = None) -> DecisionModel:
    m = model_type.lower().strip()
    if m in ("llamacpp", "clef"):
        return LlamaCppClient(endpoint=endpoint)
    if m == "jev":
        return JevAPIClient(endpoint=endpoint, api_key=api_key)
    raise ValueError(f"Unknown model type '{model_type}'. Choose from: llamacpp, clef, jev")
