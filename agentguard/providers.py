"""Provider adapters with normalized tool calls and provider-reported token usage."""

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from .models import ModelSpec


class ProviderError(RuntimeError):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class Completion:
    text: str = ""
    calls: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    usage_known: bool = True


def cost_of(spec: ModelSpec, result: Completion):
    if spec.provider == "demo":
        return 0.0
    if not result.usage_known or spec.input_per_million is None or spec.output_per_million is None:
        return None
    return (
        result.input_tokens * spec.input_per_million + result.output_tokens * spec.output_per_million
    ) / 1_000_000


TOOL_SCHEMAS = {
    "knowledge_search": {
        "name": "knowledge_search",
        "description": "Search the agent's supplied knowledge documents.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "lookup_order": {
        "name": "lookup_order",
        "description": "Look up an order in the local demonstration order fixture (not a real CRM).",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
}


class ProviderClient:
    def __init__(self, transport=None):
        self.transport = transport

    def complete(
        self, spec: ModelSpec, messages: list[dict], tools: list[str], max_tokens=1024
    ) -> Completion:
        if spec.provider == "demo":
            return self._demo(messages, tools)
        env = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}[
            spec.provider
        ]
        key = os.getenv(env)
        if not key:
            raise ProviderError(f"{env} is not configured", retryable=True)
        schemas = [TOOL_SCHEMAS[t] for t in tools]
        if spec.provider == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {key}"}
            converted = []
            for m in messages:
                entry = dict(m)
                if m.get("tool_calls"):
                    entry["tool_calls"] = [
                        {k: c[k] for k in ("id", "type", "function")} for c in m["tool_calls"]
                    ]
                converted.append(entry)
            body: dict[str, Any] = {
                "model": spec.model,
                "messages": converted,
                "max_completion_tokens": max_tokens,
            }
            if schemas:
                body["tools"] = [{"type": "function", "function": s} for s in schemas]
        elif spec.provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            converted = []
            for m in messages:
                if m["role"] == "system":
                    continue
                if m["role"] == "tool":
                    converted.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": m["tool_call_id"],
                                    "content": m["content"],
                                }
                            ],
                        }
                    )
                elif m.get("tool_calls"):
                    content = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                    content += [
                        {
                            "type": "tool_use",
                            "id": c["id"],
                            "name": c["function"]["name"],
                            "input": json.loads(c["function"]["arguments"]),
                        }
                        for c in m["tool_calls"]
                    ]
                    converted.append({"role": "assistant", "content": content})
                else:
                    converted.append({"role": m["role"], "content": m["content"]})
            body = {
                "model": spec.model,
                "max_tokens": max_tokens,
                "system": "\n".join(m["content"] for m in messages if m["role"] == "system"),
                "messages": converted,
            }
            if schemas:
                body["tools"] = [
                    {"name": s["name"], "description": s["description"], "input_schema": s["parameters"]}
                    for s in schemas
                ]
        else:
            from urllib.parse import quote

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(spec.model, safe='')}:generateContent"
            headers = {"x-goog-api-key": key}
            converted = []
            call_names = {}
            for m in messages:
                if m["role"] == "system":
                    continue
                if m["role"] == "tool":
                    parts = [
                        {
                            "functionResponse": {
                                "name": call_names[m["tool_call_id"]],
                                "response": {"result": m["content"]},
                            }
                        }
                    ]
                else:
                    parts = [{"text": m["content"]}] if m.get("content") else []
                    for c in m.get("tool_calls", []):
                        call_names[c["id"]] = c["function"]["name"]
                        part = {
                            "functionCall": {
                                "name": c["function"]["name"],
                                "args": json.loads(c["function"]["arguments"]),
                            }
                        }
                        if c.get("thought_signature"):
                            part["thoughtSignature"] = c["thought_signature"]
                        parts.append(part)
                converted.append({"role": "model" if m["role"] == "assistant" else "user", "parts": parts})
            body = {
                "contents": converted,
                "systemInstruction": {
                    "parts": [{"text": "\n".join(m["content"] for m in messages if m["role"] == "system")}]
                },
                "generationConfig": {"maxOutputTokens": max_tokens},
            }
            if schemas:
                body["tools"] = [
                    {
                        "functionDeclarations": [
                            {
                                "name": s["name"],
                                "description": s["description"],
                                "parametersJsonSchema": s["parameters"],
                            }
                            for s in schemas
                        ]
                    }
                ]
        try:
            with httpx.Client(timeout=httpx.Timeout(60, connect=10), transport=self.transport) as client:
                response = client.post(url, headers=headers, json=body)
        except httpx.TransportError as exc:
            raise ProviderError(f"{spec.provider} transport failure", retryable=True) from exc
        if response.status_code >= 400:
            # Never store raw error bodies, which may echo prompts or credentials.
            raise ProviderError(
                f"{spec.provider} HTTP {response.status_code}",
                retryable=response.status_code in (408, 429) or response.status_code >= 500,
            )
        try:
            data = response.json()
            if spec.provider == "openai":
                if data["choices"][0].get("finish_reason") in ("length", "content_filter"):
                    raise ProviderError("openai output was truncated or filtered")
                message = data["choices"][0]["message"]
                usage = data.get("usage") or {}
                return Completion(
                    message.get("content") or "",
                    message.get("tool_calls") or [],
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                    "prompt_tokens" in usage and "completion_tokens" in usage,
                )
            if spec.provider == "anthropic":
                if data.get("stop_reason") in ("max_tokens", "refusal", "pause_turn"):
                    raise ProviderError("anthropic did not complete the response")
                usage = data.get("usage") or {}
                calls = [
                    {
                        "id": p["id"],
                        "type": "function",
                        "function": {"name": p["name"], "arguments": json.dumps(p["input"])},
                    }
                    for p in data["content"]
                    if p["type"] == "tool_use"
                ]
                # Cache pricing is model-specific; cached usage requires separate accounting.
                known = (
                    "input_tokens" in usage
                    and "output_tokens" in usage
                    and not usage.get("cache_read_input_tokens")
                    and not usage.get("cache_creation_input_tokens")
                )
                return Completion(
                    "".join(p["text"] for p in data["content"] if p["type"] == "text"),
                    calls,
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                    bool(known),
                )
            if data["candidates"][0].get("finishReason", "STOP") != "STOP":
                raise ProviderError("gemini did not complete the response")
            parts = data["candidates"][0]["content"]["parts"]
            usage = data.get("usageMetadata") or {}
            calls = [
                {
                    "id": f"gemini-{i}",
                    "type": "function",
                    "function": {
                        "name": p["functionCall"]["name"],
                        "arguments": json.dumps(p["functionCall"].get("args", {})),
                    },
                    **({"thought_signature": p["thoughtSignature"]} if p.get("thoughtSignature") else {}),
                }
                for i, p in enumerate(parts)
                if "functionCall" in p
            ]
            known = (
                "promptTokenCount" in usage
                and "candidatesTokenCount" in usage
                and not usage.get("cachedContentTokenCount")
            )
            return Completion(
                "".join(p["text"] for p in parts if "text" in p and not p.get("thought")),
                calls,
                usage.get("promptTokenCount", 0),
                usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
                bool(known),
            )
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{spec.provider} returned an unsupported response") from exc

    @staticmethod
    def _demo(messages, tools):
        import re

        user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        if messages[-1]["role"] == "tool":
            output = messages[-1]["content"]
        elif "lookup_order" in tools and re.search(r"order\s+#?(\d+)", user, re.I):
            order_id = re.search(r"order\s+#?(\d+)", user, re.I).group(1)
            return Completion(
                calls=[
                    {
                        "id": "demo-order",
                        "type": "function",
                        "function": {"name": "lookup_order", "arguments": json.dumps({"order_id": order_id})},
                    }
                ]
            )
        elif "knowledge_search" in tools:
            return Completion(
                calls=[
                    {
                        "id": "demo-search",
                        "type": "function",
                        "function": {"name": "knowledge_search", "arguments": json.dumps({"query": user})},
                    }
                ]
            )
        else:
            evidence = next(
                (
                    m["content"].split("EVIDENCE_JSON:\n", 1)[1]
                    for m in messages
                    if "EVIDENCE_JSON:\n" in m.get("content", "")
                ),
                "[]",
            )
            docs = json.loads(evidence)
            output = docs[0]["text"] if docs else "I do not know based on the supplied evidence."
            # This offline fixture cannot infer eligibility for used items from
            # a policy about unused items. Do not imply either approval or denial.
            if (
                re.search(r"\breturn\b", user, re.I)
                and re.search(r"\bused\b|\bnot\s+unused\b", user, re.I)
                and re.search(r"\bunused\b", output, re.I)
            ):
                output = (
                    "The supplied policy covers unused items. "
                    "I cannot determine whether a used item is eligible for return from this evidence."
                )
        # Deterministic fixture: token counts are estimates, never provider usage.
        return Completion(
            output,
            input_tokens=sum(len(m.get("content") or "") for m in messages) // 4,
            output_tokens=max(1, len(output) // 4),
        )
