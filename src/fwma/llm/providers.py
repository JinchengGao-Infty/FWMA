"""LLM provider implementations — Claude, Gemini, GPT, OpenAI-compatible."""
from __future__ import annotations
import copy
import json
import logging
import os
import time
from typing import Any
import requests

logger = logging.getLogger(__name__)


# ── Retry configuration ──────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds, doubles each retry
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
MIN_CALL_INTERVAL = 0.5  # seconds between LLM calls
_last_call_time: dict[str, float] = {}  # per-provider timestamp


def _rate_limit_wait(provider: str) -> None:
    """Enforce minimum interval between calls to the same provider."""
    now = time.time()
    last = _last_call_time.get(provider, 0)
    wait = MIN_CALL_INTERVAL - (now - last)
    if wait > 0:
        logger.debug(f"Rate limit: waiting {wait:.1f}s before calling {provider}")
        time.sleep(wait)
    _last_call_time[provider] = time.time()


def _call_with_retry(
    fn: callable,
    provider: str,
    *args: Any,
    **kwargs: Any,
) -> requests.Response:
    """Execute HTTP call with exponential backoff retry on transient errors."""
    _rate_limit_wait(provider)
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = fn(*args, **kwargs)
            if response.status_code in RETRY_STATUS_CODES:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    f"{provider} returned {response.status_code}, "
                    f"retry {attempt + 1}/{MAX_RETRIES} in {delay:.0f}s"
                )
                if attempt < MAX_RETRIES:
                    time.sleep(delay)
                    continue
                response.raise_for_status()
            return response
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                f"{provider} {type(e).__name__}, "
                f"retry {attempt + 1}/{MAX_RETRIES} in {delay:.0f}s"
            )
            if attempt < MAX_RETRIES:
                time.sleep(delay)
                continue
            raise
    raise last_exc or RuntimeError(f"{provider} call failed after {MAX_RETRIES} retries")

# Default base URLs
DEFAULT_URLS = {
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
    "gemini-openai": None,  # OpenAI-compatible Gemini endpoint
    "openai": "https://api.openai.com",
}

# Environment variable names for API keys
KEY_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}

# Environment variable names for base URLs
URL_ENV_VARS = {
    "anthropic": "ANTHROPIC_BASE_URL",
    "gemini": "GEMINI_BASE_URL",
    "gemini-openai": "GEMINI_OPENAI_BASE_URL",
    "openai": "OPENAI_BASE_URL",
}


def get_api_key(provider: str) -> str:
    """Get API key for provider from environment."""
    env_var = KEY_ENV_VARS.get(provider, f"{provider.upper()}_API_KEY")
    key = os.environ.get(env_var, "")
    if not key:
        raise ValueError(f"API key not found. Set {env_var} environment variable.")
    return key


def get_base_url(provider: str) -> str | None:
    """Get base URL for provider from environment or defaults."""
    env_var = URL_ENV_VARS.get(provider)
    if env_var:
        url = os.environ.get(env_var)
        if url:
            return url
    return DEFAULT_URLS.get(provider)


def call_anthropic(
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    max_tokens: int = 8192,
    **kwargs: Any,
) -> str:
    """Call Anthropic Claude API (native format)."""
    api_key = api_key or get_api_key("anthropic")
    base_url = base_url or get_base_url("anthropic")
    safe_messages = copy.deepcopy(messages)

    url = f"{base_url}/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": safe_messages,
    }
    if system_prompt:
        payload["system"] = system_prompt
        prefix = f"[系统指令]\n{system_prompt}\n[/系统指令]\n\n"
        for msg in safe_messages:
            if msg.get("role") == "user":
                msg["content"] = prefix + msg.get("content", "")
                break

    logger.debug(f"Calling Anthropic: {model}")
    response = _call_with_retry(requests.post, "anthropic", url, headers=headers, json=payload, timeout=120)

    data = response.json()

    if "error" in data:
        raise RuntimeError(f"Anthropic API error: {data['error']}")

    content = data.get("content", [])
    return content[0].get("text", "") if content else ""


def call_gemini_native(
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    max_tokens: int = 8192,
    **kwargs: Any,
) -> str:
    """Call Google Gemini API (native format with SSE streaming)."""
    api_key = api_key or get_api_key("gemini")
    base_url = base_url or get_base_url("gemini")

    url = f"{base_url}/v1beta/models/{model}:streamGenerateContent?alt=sse"

    # Build contents in Gemini native format
    contents = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    payload: dict[str, Any] = {"contents": contents}
    if system_prompt:
        payload["system_instruction"] = {"parts": [{"text": system_prompt}]}

    logger.debug(f"Calling Gemini native: {model}")
    response = _call_with_retry(
        requests.post, "gemini", url,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        json=payload, timeout=120, stream=True,
    )

    # Parse SSE stream
    full_text = []
    for line in response.iter_lines():
        if not line:
            continue
        line_str = line.decode("utf-8") if isinstance(line, bytes) else line
        if line_str.startswith("data: "):
            json_str = line_str[6:]
            try:
                chunk = json.loads(json_str)
                candidates = chunk.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        if "text" in part:
                            full_text.append(part["text"])
            except json.JSONDecodeError:
                continue

    return "".join(full_text)


def call_openai_format(
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    max_tokens: int = 8192,
    provider: str = "openai",
    **kwargs: Any,
) -> str:
    """Call any OpenAI-compatible API (OpenAI, Gemini, vLLM, Ollama, etc.)."""
    api_key = api_key or get_api_key(provider)
    base_url = base_url or get_base_url(provider)

    if not base_url:
        raise ValueError(f"No base URL configured for provider '{provider}'")

    # Ensure URL ends with /chat/completions
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        if not url.endswith("/v1"):
            url += "/v1"
        url += "/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Prepend system message if provided
    all_messages = []
    if system_prompt:
        all_messages.append({"role": "system", "content": system_prompt})
    all_messages.extend(messages)

    payload = {
        "model": model,
        "messages": all_messages,
        "max_tokens": max_tokens,
    }

    logger.debug(f"Calling OpenAI-format: {model} at {url}")
    response = _call_with_retry(requests.post, provider, url, headers=headers, json=payload, timeout=120)
    data = response.json()

    if "error" in data:
        raise RuntimeError(f"API error: {data['error']}")

    choices = data.get("choices", [])
    return choices[0].get("message", {}).get("content", "") if choices else ""


def call_gemini_structured(
    model: str,
    messages: list[dict],
    response_format: Any,
    api_key: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    **kwargs: Any,
) -> Any:
    """Call Gemini with structured output (Pydantic model).

    Tries OpenAI-compatible format first, falls back to native Gemini.
    """
    api_key = api_key or get_api_key("gemini")

    # Try OpenAI-compatible format first
    openai_base = get_base_url("gemini-openai")
    if openai_base:
        try:
            url = openai_base.rstrip("/")
            if not url.endswith("/chat/completions"):
                if not url.endswith("/v1"):
                    url += "/v1"
                url += "/chat/completions"

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            all_messages = []
            if system_prompt:
                all_messages.append({"role": "system", "content": system_prompt})
            all_messages.extend(messages)

            # Build JSON schema from Pydantic model
            schema = response_format.model_json_schema() if hasattr(response_format, "model_json_schema") else {}

            payload = {
                "model": model,
                "messages": all_messages,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_format.__name__ if hasattr(response_format, "__name__") else "response",
                        "schema": schema,
                    },
                },
            }

            response = _call_with_retry(requests.post, "gemini", url, headers=headers, json=payload, timeout=120)
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            if content:
                return _parse_structured(content, response_format)
        except Exception as e:
            logger.debug(f"OpenAI-compatible structured call failed, trying native: {e}")

    # Fallback: native Gemini with JSON mode
    native_base = get_base_url("gemini")
    url = f"{native_base}/v1beta/models/{model}:generateContent"

    contents = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    payload_native: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"responseMimeType": "application/json"},
    }
    if system_prompt:
        payload_native["system_instruction"] = {"parts": [{"text": system_prompt}]}

    # Add response schema if available
    if hasattr(response_format, "model_json_schema"):
        payload_native["generationConfig"]["responseSchema"] = response_format.model_json_schema()

    response = _call_with_retry(
        requests.post, "gemini", url,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        json=payload_native, timeout=120,
    )
    data = response.json()

    content = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    return _parse_structured(content, response_format)


def _parse_structured(content: str, response_format: Any) -> Any:
    """Parse JSON content into Pydantic model with repair fallback."""
    # Clean markdown code blocks
    cleaned = content.strip()
    if cleaned.startswith("```"):
        first_nl = cleaned.find("\n")
        if first_nl != -1:
            cleaned = cleaned[first_nl + 1 :]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json

            repaired = repair_json(cleaned)
            parsed = json.loads(repaired)
        except (ImportError, Exception) as e:
            raise ValueError(f"Failed to parse structured response: {e}") from e

    if hasattr(response_format, "model_validate"):
        return response_format.model_validate(parsed)
    return parsed


# Provider dispatch table
PROVIDERS = {
    "anthropic": call_anthropic,
    "gemini": call_gemini_native,
    "openai": lambda model, messages, **kw: call_openai_format(model, messages, provider="openai", **kw),
}
