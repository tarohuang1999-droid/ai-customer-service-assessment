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
    """3-stage Choice client for /v1/systemone (llama.cpp Clef & Jev API).

    Stage 1 (classification): Merged category/sub_category choice (14 options < 20)
    Stage 2 (urgent_level): Time urgency degree choice (high / medium / low)
    Stage 3 (impact_level): Business & financial impact degree choice (high / medium / low)
    """

    def __init__(self, name: str, endpoint: str, headers: dict[str, str], timeout: float = 30.0) -> None:
        self.name = name
        self.endpoint = endpoint
        self.headers = headers
        self.timeout = timeout

    def _post_systemone(
        self,
        stage_name: str,
        state_str: str,
        questions: dict[str, Any],
        traces: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {"state": state_str, "questions": questions}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=body, headers=self.headers, method="POST")
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as http_err:
            err_body = http_err.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {http_err.code} in stage={stage_name}: {err_body}") from http_err

        ms = round((time.perf_counter() - t0) * 1000, 1)
        traces.append(
            {
                "stage": stage_name,
                "ms": ms,
                "input_tokens": data.get("usage", {}).get("input_tokens"),
                "input": payload,
                "output": data.get("answers", {}),
            }
        )
        return data

    def classify(self, state_str: str, labels_cfg: dict[str, Any]) -> ClassificationResult:
        t0 = time.perf_counter()
        traces: list[dict[str, Any]] = []
        try:
            # Stage 1: Merged classification (category/sub_category, 14 options < 20)
            t_c0 = time.perf_counter()
            clf_cfg = labels_cfg["classification"]
            merged_criteria = {
                pair_key: opt_val["description"]
                for pair_key, opt_val in clf_cfg["options"].items()
                if not opt_val.get("precheck_only", False)
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

            # Stage 2: urgent_level (choice: high / medium / low)
            t_u0 = time.perf_counter()
            urg_cfg = labels_cfg["urgent_level"]
            q_urg = {
                "urgent_level": {
                    "type": "choice",
                    "instructions": urg_cfg["instructions"],
                    "criteria": {k: v["description"] for k, v in urg_cfg["options"].items()},
                }
            }
            r2 = self._post_systemone("urgent_level", state_str, q_urg, traces)
            stage_urg_ms = round((time.perf_counter() - t_u0) * 1000, 1)
            ans2 = r2["answers"]["urgent_level"]
            urgent_level = str(ans2["choice"])
            urgent_probs = {k: round(float(v), 4) for k, v in ans2.get("probabilities", {}).items()}
            urgent_conf = float(ans2.get("confidence", urgent_probs.get(urgent_level, 0.0)))

            # Stage 3: impact_level (choice: high / medium / low)
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
                category="unknown",
                sub_category="insufficient_info",
                confidence=0.0,
                urgent_level="low",
                urgent_conf=0.0,
                impact_level="low",
                impact_conf=0.0,
                model_name=self.name,
                stage_classification_ms=elapsed,
                model_traces=traces,
                error=f"{type(exc).__name__}: {exc}",
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
    """Remote Jev Decision Model API client (/v1/systemone)."""

    def __init__(self, endpoint: str | None = None, api_key: str | None = None, timeout: float = 30.0) -> None:
        url = endpoint or os.environ.get("JEV_API_URL", "https://api.jev.ai/v1/systemone")
        key = api_key or os.environ.get("JEV_API_KEY", "")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        super().__init__(name="jev-api", endpoint=url, headers=headers, timeout=timeout)


class MockDecisionModel:
    """Offline keyword-scoring baseline matching the 3-stage Choice interface."""

    name = "mock-baseline"

    _PAIR_KEYWORDS: dict[str, list[str]] = {
        "other_non_cs/b2b_media_hr_referral": ["企業包團", "員工旅遊", "包車報價", "應徵", "履歷", "業配", "互惠合作", "媒體採訪", "記者"],
        "complaint/pure_complaint": ["電話是裝飾品", "電話都打不通", "40 分鐘沒人接"],
        "complaint/service_or_billing_dispute": ["導遊態度差", "行程縮水", "重複扣款", "消保官", "領隊遲到", "錯過班機", "蟑螂", "回錯資訊", "多收"],
        "order_refund/cancellation_refund_request": ["想取消行程", "住院", "骨折開刀", "全額退費", "颱風會不會延期"],
        "order_refund/refund_payout_request": ["匯到我台灣銀行帳戶", "退款請匯到"],
        "order_change/schedule_or_group_change": ["想改期", "change my pickup", "Change pickup hotel", "2 人退出"],
        "order_change/passenger_or_addon_change": ["加購嬰兒票", "英文名拼錯", "加購托運行李", "加購行李"],
        "order_info/account_and_pricing_issue": ["帳號被鎖", "無法登入", "價格與結帳金額不同", "標價錯誤"],
        "order_info/document_and_invoice": ["未收到確認信", "發票統編打錯", "三聯式發票", "沒收到電子票券", "QR code", "英文收據", "invoice"],
        "order_info/order_policy_and_refund_status": ["手續費是收百分之多少", "定型化契約", "多久會入帳"],
        "order_info/order_status_and_points": ["行程表何時寄出", "出發通知何時會來", "旺來金", "折抵"],
        "product_inquiry/customization_request": ["指定樓層", "指定高樓層", "素食餐", "全素", "輪椅", "無障礙房"],
        "product_inquiry/policy_and_regulation": ["護照效期", "效期剩不到六個月", "落地簽", "簽證規定"],
        "product_inquiry/product_spec_and_price": ["費用內含項目", "導遊小費", "2 歲小孩收費", "JR PASS", "哪裡兌換", "大雪導致巴士停駛"],
    }

    def classify(self, state_str: str, labels_cfg: dict[str, Any]) -> ClassificationResult:
        t0 = time.perf_counter()
        pair_scores: dict[str, float] = {}
        for pair, opt_val in labels_cfg["classification"]["options"].items():
            if opt_val.get("precheck_only", False):
                continue
            pair_scores[pair] = 0.1
            for kw in self._PAIR_KEYWORDS.get(pair, []):
                if kw in state_str:
                    pair_scores[pair] += 2.0

        total = sum(pair_scores.values())
        probs = {k: round(v / total, 4) for k, v in pair_scores.items()}
        best_pair = max(probs, key=lambda k: probs[k])
        best_cat, best_sub = best_pair.split("/", 1)
        conf = min(0.95, round(probs[best_pair] + 0.45, 4)) if pair_scores[best_pair] > 0.1 else 0.45

        urg_level = "high" if any(k in state_str for k in ["明天", "蟑螂", "帳號被鎖"]) else "low"
        imp_level = "high" if any(k in state_str for k in ["消保官", "重複扣款", "186,000", "45,000", "導遊態度差"]) else "low"
        elapsed = round((time.perf_counter() - t0) * 1000, 2)

        return ClassificationResult(
            category=best_cat,
            sub_category=best_sub,
            confidence=conf,
            urgent_level=urg_level,
            urgent_conf=0.90,
            impact_level=imp_level,
            impact_conf=0.90,
            model_name=self.name,
            stage_classification_ms=elapsed,
            classification_probs=probs,
            urgent_probs={urg_level: 0.90},
            impact_probs={imp_level: 0.90},
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
