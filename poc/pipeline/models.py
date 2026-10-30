from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class ClassificationResult:
    category: str
    sub_category: str
    category_conf: float
    sub_category_conf: float
    confidence: float
    is_urgent_prob: float
    is_high_impact_prob: float
    model_name: str
    category_probs: dict[str, float] = field(default_factory=dict)
    sub_category_probs: dict[str, float] = field(default_factory=dict)
    error: str | None = None


class DecisionModel(Protocol):
    name: str

    def classify(self, state_str: str, labels_cfg: dict[str, Any]) -> ClassificationResult: ...


class _SystemOneHTTPBase:
    """Shared two-stage hierarchical client for /v1/systemone (llama.cpp Clef & Jev API)."""

    def __init__(self, name: str, endpoint: str, headers: dict[str, str], timeout: float = 30.0) -> None:
        self.name = name
        self.endpoint = endpoint
        self.headers = headers
        self.timeout = timeout

    def _post_systemone(self, state_str: str, questions: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"state": state_str, "questions": questions}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=body, headers=self.headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def classify(self, state_str: str, labels_cfg: dict[str, Any]) -> ClassificationResult:
        try:
            # Stage 1: Main Category (5 choices, keeping input_tokens well below 512 batch limit)
            cat_criteria = {
                k: v["description"]
                for k, v in labels_cfg["categories"].items()
                if k != "unknown"
            }
            stage1_q = {
                "category": {
                    "type": "choice",
                    "instructions": labels_cfg["stage1"]["category_instructions"],
                    "criteria": cat_criteria,
                }
            }
            r1 = self._post_systemone(state_str, stage1_q)
            cat_ans = r1["answers"]["category"]
            category = str(cat_ans["choice"])
            cat_probs = {k: float(v) for k, v in cat_ans.get("probabilities", {}).items()}
            cat_conf = float(cat_ans.get("confidence", cat_probs.get(category, 0.0)))

            # Stage 2: Sub-category (2-3 choices)
            sub_group = labels_cfg["sub_categories"][category]
            sub_options = sub_group["options"]
            if len(sub_options) == 1:
                sub_cat = next(iter(sub_options))
                sub_probs = {sub_cat: 1.0}
                sub_conf = cat_conf
            else:
                stage2_q: dict[str, Any] = {
                    "sub_category": {
                        "type": "choice",
                        "instructions": sub_group["instructions"],
                        "criteria": {k: v["description"] for k, v in sub_options.items()},
                    }
                }
                r2 = self._post_systemone(state_str, stage2_q)
                sub_ans = r2["answers"]["sub_category"]
                sub_cat = str(sub_ans["choice"])
                sub_probs = {k: float(v) for k, v in sub_ans.get("probabilities", {}).items()}
                sub_conf = float(sub_ans.get("confidence", sub_probs.get(sub_cat, 0.0)))

            # Stage 3: Urgency & Impact (2 lightweight noul questions)
            stage3_q: dict[str, Any] = {
                "is_urgent": {
                    "type": "noul",
                    "instructions": labels_cfg["stage1"]["urgency_instructions"],
                },
                "is_high_impact": {
                    "type": "noul",
                    "instructions": labels_cfg["stage1"]["impact_instructions"],
                },
            }
            r3 = self._post_systemone(state_str, stage3_q)
            ans3 = r3["answers"]
            urgent_prob = float(ans3["is_urgent"]["noul"])
            impact_prob = float(ans3["is_high_impact"]["noul"])

            combined_conf = round(min(cat_conf, sub_conf), 4)
            return ClassificationResult(
                category=category,
                sub_category=sub_cat,
                category_conf=round(cat_conf, 4),
                sub_category_conf=round(sub_conf, 4),
                confidence=combined_conf,
                is_urgent_prob=round(urgent_prob, 4),
                is_high_impact_prob=round(impact_prob, 4),
                model_name=self.name,
                category_probs=cat_probs,
                sub_category_probs=sub_probs,
            )
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError) as exc:
            return ClassificationResult(
                category="unknown",
                sub_category="insufficient_info",
                category_conf=0.0,
                sub_category_conf=0.0,
                confidence=0.0,
                is_urgent_prob=0.0,
                is_high_impact_prob=0.0,
                model_name=self.name,
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
    """Offline hierarchical keyword-scoring baseline implementing the same 2-stage flow."""

    name = "mock-baseline"

    _SUB_KEYWORDS: dict[str, list[str]] = {
        "spam_or_test": ["博弈", "體驗金", "儲值再送", "加賴好友"],
        "b2b_media_hr_referral": ["企業包團", "員工旅遊", "包車報價", "應徵", "履歷", "業配", "互惠合作", "媒體採訪", "記者"],
        "pure_complaint": ["電話是裝飾品", "電話都打不通", "40 分鐘沒人接"],
        "service_or_billing_dispute": ["導遊態度差", "行程縮水", "重複扣款", "消保官", "領隊遲到", "錯過班機", "蟑螂", "回錯資訊", "多收"],
        "refund_change_policy_general": ["手續費是收百分之多少", "定型化契約", "多久會入帳", "大雪導致巴士停駛"],
        "order_modification": ["加購嬰兒票", "想改期", "change my pickup", "Change pickup hotel", "英文名拼錯", "2 人退出", "加購托運行李", "加購行李"],
        "order_cancellation_refund": ["想取消行程", "住院", "骨折開刀", "全額退費", "颱風會不會延期", "匯到我台灣銀行帳戶", "退款請匯到"],
        "account_and_pricing_issue": ["帳號被鎖", "無法登入", "價格與結帳金額不同", "標價錯誤"],
        "document_reissue_and_invoice": ["未收到確認信", "發票統編打錯", "三聯式發票", "沒收到電子票券", "QR code", "英文收據", "invoice"],
        "order_status_and_points": ["行程表何時寄出", "出發通知何時會來", "旺來金", "折抵"],
        "customization_request": ["指定樓層", "指定高樓層", "素食餐", "全素", "輪椅", "無障礙房"],
        "policy_and_regulation": ["護照效期", "效期剩不到六個月", "落地簽", "簽證規定"],
        "product_spec_and_price": ["費用內含項目", "導遊小費", "2 歲小孩收費", "JR PASS", "哪裡兌換"],
    }

    def classify(self, state_str: str, labels_cfg: dict[str, Any]) -> ClassificationResult:
        scores: dict[str, float] = {cat: 0.1 for cat in labels_cfg["categories"]}
        sub_scores: dict[str, dict[str, float]] = {
            cat: {sub: 0.1 for sub in labels_cfg["sub_categories"][cat]["options"]}
            for cat in labels_cfg["categories"]
        }

        for cat, group in labels_cfg["sub_categories"].items():
            for sub in group["options"]:
                for kw in self._SUB_KEYWORDS.get(sub, []):
                    if kw in state_str:
                        scores[cat] += 1.5
                        sub_scores[cat][sub] += 2.0

        # Normalize Stage 1 probabilities
        total_cat = sum(scores.values())
        cat_probs = {k: round(v / total_cat, 4) for k, v in scores.items()}
        best_cat = max(cat_probs, key=lambda k: cat_probs[k])
        cat_conf = min(0.95, round(cat_probs[best_cat] + 0.35, 4)) if scores[best_cat] > 0.1 else 0.45

        # Normalize Stage 2 probabilities within best_cat
        s_map = sub_scores[best_cat]
        total_sub = sum(s_map.values())
        sub_probs = {k: round(v / total_sub, 4) for k, v in s_map.items()}
        best_sub = max(sub_probs, key=lambda k: sub_probs[k])
        sub_conf = min(0.96, round(sub_probs[best_sub] + 0.30, 4)) if s_map[best_sub] > 0.1 else 0.45

        urgent_p = 0.88 if any(k in state_str for k in ["明天", "蟑螂", "帳號被鎖"]) else 0.08
        impact_p = 0.90 if any(k in state_str for k in ["消保官", "重複扣款", "186,000", "45,000", "導遊態度差"]) else 0.10

        return ClassificationResult(
            category=best_cat,
            sub_category=best_sub,
            category_conf=cat_conf,
            sub_category_conf=sub_conf,
            confidence=round(min(cat_conf, sub_conf), 4),
            is_urgent_prob=urgent_p,
            is_high_impact_prob=impact_p,
            model_name=self.name,
            category_probs=cat_probs,
            sub_category_probs=sub_probs,
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
