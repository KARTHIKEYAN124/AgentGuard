import json
import re

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from .models import Metrics


def validate_schema_definition(schema):
    """Validate without allowing remote reference retrieval during later evaluation."""

    def inspect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("$ref", "$dynamicRef") and isinstance(item, str) and not item.startswith("#"):
                    raise ValueError("Only local JSON Schema references are supported")
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    inspect(schema)
    Draft202012Validator.check_schema(schema)


def evaluate_schema(output: str | dict, schema: dict | type[BaseModel]) -> dict:
    try:
        data = json.loads(output) if isinstance(output, str) else output
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            schema.model_validate(data, strict=True)
            errors = []
        else:
            validate_schema_definition(schema)
            errors = [
                f"{'/'.join(map(str, e.path)) or '/'}: {e.message}"
                for e in Draft202012Validator(schema).iter_errors(data)
            ]
        return {"passed": not errors, "errors": errors, "method": "schema_validation"}
    except (json.JSONDecodeError, ValidationError) as exc:
        return {"passed": False, "errors": [str(exc)], "method": "schema_validation"}


def words(text):
    return set(re.findall(r"\b\w+\b", text.lower()))


def evaluate_faithfulness(answer: str, sources: list[str]) -> dict:
    """Lexical screening only; use a live judge for semantic assessment."""
    if not sources or not answer.strip():
        return {
            "score": None,
            "method": "lexical_overlap",
            "reason": "Missing answer or evidence",
            "unsupported_claims": [],
        }
    evidence = words(" ".join(sources))
    claims = [c.strip() for c in re.split(r"(?<=[.!?])\s+", answer) if c.strip()]
    scores = [len(words(c) & evidence) / max(len(words(c)), 1) for c in claims]
    return {
        "score": sum(scores) / len(scores),
        "method": "lexical_overlap",
        "unsupported_claims": [c for c, s in zip(claims, scores, strict=True) if s < 0.6],
        "warning": "Token overlap is not proof of support and cannot detect negation or factual contradictions. A score of 1 does not establish answer correctness or relevance to the question.",
    }


def evaluate_retrieval(query: str, expected_docs: list[str], retrieved_docs: list[str], k: int = 5) -> dict:
    if k < 1:
        raise ValueError("k must be positive")
    ranked = list(dict.fromkeys(retrieved_docs))[:k]
    expected = set(expected_docs)
    hits = sum(d in expected for d in ranked)
    return {
        "query": query,
        "k": k,
        "precision_at_k": hits / k,
        "recall_at_k": hits / len(expected) if expected else None,
        "mrr": next((1 / i for i, d in enumerate(ranked, 1) if d in expected), 0.0) if expected else None,
    }


def detect_regression(current: dict | Metrics, baseline: dict | Metrics) -> dict:
    current = Metrics.model_validate(current).model_dump()
    baseline = Metrics.model_validate(baseline).model_dump()

    def increase(now, before):
        if now is None or before is None:
            return None
        if before == 0:
            return 0.0 if now == 0 else None
        return (now - before) / before

    drop = baseline["accuracy"] - current["accuracy"]
    cost = increase(current["cost"], baseline["cost"])
    latency = increase(current["latency_ms"], baseline["latency_ms"])
    checks = [
        {
            "metric": "accuracy",
            "change": drop,
            "limit": 0.03,
            "unit": "absolute_fraction",
            "passed": drop <= 0.03 + 1e-12,
        },
        {
            "metric": "cost",
            "change": cost,
            "limit": 0.20,
            "unit": "relative_fraction",
            "passed": cost is not None and cost <= 0.20 + 1e-12,
        },
        {
            "metric": "latency_ms",
            "change": latency,
            "limit": 0.30,
            "unit": "relative_fraction",
            "passed": latency is not None and latency <= 0.30 + 1e-12,
        },
    ]
    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "reason": "Unknown costs and increases from zero block the gate; accuracy uses percentage points.",
    }
