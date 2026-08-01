"""Secret redaction and integrity helpers."""

import hashlib
import hmac
import json
import re
from typing import Any

SENSITIVE_KEY = re.compile(r"(api[-_]?key|authorization|password|secret|token|cookie)", re.I)
BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=True)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sign_json(value: Any, secret: str) -> str:
    return hmac.new(secret.encode(), canonical_json(value).encode(), hashlib.sha256).hexdigest()


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]" if SENSITIVE_KEY.search(str(k)) else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return BEARER.sub("Bearer [REDACTED]", value)
    return value


def contains_prompt_injection(text: str) -> bool:
    patterns = (
        "ignore previous instructions",
        "reveal system prompt",
        "reveal secrets",
        "call this tool",
        "override system policy",
    )
    lowered = text.casefold()
    return any(pattern in lowered for pattern in patterns)
