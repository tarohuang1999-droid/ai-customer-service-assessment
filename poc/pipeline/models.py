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


class MockDecisionModel:
    """Offline baseline: scores options with a generic keyword lexicon (no sample sentences).
    Only used to run the pipeline without a model server; real routing relies on the decision model.

    It only proves the pipeline runs end-to-end without a model server; its accuracy
    is expected to be well below the decision model.
    """

    name = "mock-baseline"

    _LEXICON: dict[str, list[str]] = {
        "product/product_info": ["費用", "價格", "多少錢", "包含", "小費", "收費", "兌換", "票券", "艙房", "座位", "加購"],
        "product/travel_rule": ["護照", "簽證", "入境", "效期", "颱風", "大雪", "天候", "停駛", "停航"],
        "product/cancel_policy": ["手續費", "定型化契約", "級距", "取消規定"],
        "product/custom_request": ["包團", "企業", "無障礙", "輪椅", "素食", "客製", "指定"],
        "order_inquiry/order_status": ["確認信", "訂單是否成立", "行程表", "出發通知", "行前通知", "何時寄", "什麼時候寄"],
        "order_inquiry/refund_status": ["入帳", "退款進度", "退回信用卡"],
        "order_inquiry/document": ["收據", "invoice", "憑證", "QR code", "電子票", "補寄"],
        "order_inquiry/member_points": ["點數", "紅利", "折抵"],
        "order_change/booking_change": ["改期", "改到", "更改", "change", "退出", "人數", "想取消", "退費", "帳戶"],
        "order_change/data_correction": ["拼錯", "打錯", "更正", "重開", "改開", "統編"],
        "system_issue/account_access": ["登入", "帳號", "密碼", "驗證碼", "鎖定"],
        "system_issue/checkout_error": ["扣款", "重複扣", "結帳", "付款失敗", "刷卡失敗", "標價"],
        "trip_incident/disruption": ["入住", "房間", "換房", "遺失", "受傷", "滯留", "沒出現"],
        "complaint/service_complaint": ["打不通", "沒人接", "服務態度", "等很久"],
        "complaint/compensation_claim": ["賠償", "求償", "退還", "道歉", "消保官", "申訴", "損失"],
        "other/business": ["報價單", "合作", "業配", "採訪", "記者", "應徵", "履歷", "職缺", "包車"],
        "other/irrelevant": ["廣告", "博弈", "優惠活動", "測試", "自動回覆"],
        "other/unclear": [],
    }
    _URGENCY = {"high": ["今天", "明天", "明日", "今晚", "後天", "旅途中", "現在人在"], "medium": ["下週", "急", "期限", "截止", "報帳"]}
    _IMPACT = {
        "high": ["賠償", "求償", "重複扣", "消保官", "媒體", "律師", "受傷"],
        "medium": ["改期", "取消", "退費", "更正", "加購", "改開", "重開", "帳號", "付款"],
    }

    @staticmethod
    def _level(text: str, lexicon: dict[str, list[str]]) -> str:
        for level in ("high", "medium"):
            if any(k in text for k in lexicon[level]):
                return level
        return "low"

    def classify(self, state_str: str, labels_cfg: dict[str, Any]) -> ClassificationResult:
        t0 = time.perf_counter()
        scores = {k: 0.1 for k in labels_cfg["classification"]["options"]}
        for key, words in self._LEXICON.items():
            if key in scores:
                scores[key] += sum(1.0 for w in words if w in state_str)
        body_len = len(state_str.split("內文：", 1)[-1])
        if body_len < 8:
            scores["other/unclear"] += 1.5

        total = sum(scores.values())
        probs = {k: round(v / total, 4) for k, v in scores.items()}
        best = max(probs, key=lambda k: probs[k])
        top = scores[best]
        conf = 0.45 if top <= 0.1 else min(0.95, 0.55 + 0.15 * (top - 0.1))
        category, sub = best.split("/", 1)
        urgency = self._level(state_str, self._URGENCY)
        impact = self._level(state_str, self._IMPACT)
        elapsed = round((time.perf_counter() - t0) * 1000, 2)

        return ClassificationResult(
            category=category,
            sub_category=sub,
            confidence=round(conf, 4),
            urgent_level=urgency,
            urgent_conf=0.80,
            impact_level=impact,
            impact_conf=0.80,
            model_name=self.name,
            stage_classification_ms=elapsed,
            classification_probs=probs,
            urgent_probs={urgency: 0.80},
            impact_probs={impact: 0.80},
        )


def create_model(model_type: str, endpoint: str | None = None, api_key: str | None = None) -> DecisionModel:
    m = model_type.lower().strip()
    if m in ("llamacpp", "clef"):
        return LlamaCppClient(endpoint=endpoint)
    if m == "jev":
        return JevAPIClient(endpoint=endpoint, api_key=api_key)
    if m == "mock":
        return MockDecisionModel()
    raise ValueError(f"Unknown model type '{model_type}'. Choose from: llamacpp, clef, jev, mock")
