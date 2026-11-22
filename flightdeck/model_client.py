"""Model client for A2 (runtime): any OpenAI-compatible chat-completions endpoint, stdlib only.

Configured only from the environment, so no model name or key is ever committed:
  FLIGHTDECK_MODEL_PROVIDER   groq | openrouter | gemini | custom
  FLIGHTDECK_MODEL            model name (required)
  FLIGHTDECK_MODEL_BASE_URL   custom only
  FLIGHTDECK_MODEL_KEY_ENV    custom only: name of the env var holding the key
  FLIGHTDECK_MODEL_PRICE_IN   USD per 1M input tokens (default 0, free tiers)
  FLIGHTDECK_MODEL_PRICE_OUT  USD per 1M output tokens (default 0)
The key itself lives in the provider's variable (GROQ_API_KEY, OPENROUTER_API_KEY, GEMINI_API_KEY).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

PRESETS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
}
TIMEOUT_S = 60
RETRIES = 2
RETRY_STATUS = {429, 500, 502, 503, 504}


class ModelNotConfigured(RuntimeError):
    pass


class ModelCallFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelConfig:
    base_url: str
    model: str
    api_key: str
    price_in: float = 0.0
    price_out: float = 0.0


@dataclass(frozen=True)
class ModelReply:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str


def config_from_env(env: dict | None = None) -> ModelConfig:
    env = os.environ if env is None else env
    provider = env.get("FLIGHTDECK_MODEL_PROVIDER", "").strip().lower()
    model = env.get("FLIGHTDECK_MODEL", "").strip()
    if provider in PRESETS:
        base_url, key_env = PRESETS[provider]
    elif provider == "custom":
        base_url = env.get("FLIGHTDECK_MODEL_BASE_URL", "").strip()
        key_env = env.get("FLIGHTDECK_MODEL_KEY_ENV", "").strip()
        if not base_url or not key_env:
            raise ModelNotConfigured("custom provider needs FLIGHTDECK_MODEL_BASE_URL and FLIGHTDECK_MODEL_KEY_ENV")
    else:
        raise ModelNotConfigured(f"set FLIGHTDECK_MODEL_PROVIDER to one of {sorted(PRESETS) + ['custom']}")
    if not model:
        raise ModelNotConfigured("set FLIGHTDECK_MODEL to the model name")
    key = env.get(key_env, "").strip()
    if not key:
        raise ModelNotConfigured(f"export {key_env} with your API key")
    return ModelConfig(base_url=base_url.rstrip("/"), model=model, api_key=key,
                       price_in=float(env.get("FLIGHTDECK_MODEL_PRICE_IN", 0) or 0),
                       price_out=float(env.get("FLIGHTDECK_MODEL_PRICE_OUT", 0) or 0))


def chat_json(cfg: ModelConfig, system: str, user: str) -> ModelReply:
    """One chat completion asking for a JSON object. Retries only transient failures."""
    body = json.dumps({
        "model": cfg.model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(f"{cfg.base_url}/chat/completions", data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {cfg.api_key}",
                                          "User-Agent": "flightdeck-pilot"})
    last = None
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                data = json.loads(resp.read())
            break
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in RETRY_STATUS or attempt == RETRIES:
                detail = exc.read().decode(errors="replace")[:300]
                raise ModelCallFailed(f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt == RETRIES:
                raise ModelCallFailed(f"connection failed: {exc}") from exc
        time.sleep(2 ** attempt * 2)
    else:   # pragma: no cover
        raise ModelCallFailed(str(last))

    choice = (data.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    usage = data.get("usage") or {}
    tin, tout = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
    cost = round(tin / 1e6 * cfg.price_in + tout / 1e6 * cfg.price_out, 6)
    return ModelReply(text=text, input_tokens=tin, output_tokens=tout, cost_usd=cost,
                      model=data.get("model") or cfg.model)
