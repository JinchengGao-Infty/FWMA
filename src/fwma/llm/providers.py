"""LLM provider implementations — Claude, Gemini, GPT, OpenAI-compatible."""
from __future__ import annotations

import copy
import json
import logging
import multiprocessing.connection
import os
import threading
import time
import traceback
from multiprocessing import get_context
from typing import Any

import requests
from requests.structures import CaseInsensitiveDict

logger = logging.getLogger(__name__)


# ── Retry configuration ──────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds, doubles each retry
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
MIN_CALL_INTERVAL = 0.5  # seconds between LLM calls
_last_call_time: dict[str, float] = {}  # per-provider timestamp
_rate_limit_lock = threading.Lock()
DEFAULT_HARD_TIMEOUT_SECONDS = 360.0
HTTP_METHOD_NAMES = {"delete", "get", "patch", "post", "put"}


def _rate_limit_wait(provider: str) -> None:
    """Enforce minimum interval between calls to the same provider."""
    wait = 0.0
    with _rate_limit_lock:
        now = time.time()
        last = _last_call_time.get(provider, 0)
        wait = MIN_CALL_INTERVAL - (now - last)
        if wait <= 0:
            _last_call_time[provider] = now
    if wait > 0:
        logger.debug(f"Rate limit: waiting {wait:.1f}s before calling {provider}")
        time.sleep(wait)
        with _rate_limit_lock:
            _last_call_time[provider] = time.time()


def _serialize_response(response: requests.Response) -> dict[str, Any]:
    """Convert a requests.Response into a pipe-safe payload."""
    return {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "content": response.content,
        "url": response.url,
        "reason": response.reason,
        "encoding": response.encoding,
    }


def _deserialize_response(payload: dict[str, Any]) -> requests.Response:
    """Rebuild a minimal Response object from serialized data."""
    response = requests.Response()
    response.status_code = payload["status_code"]
    response.headers = CaseInsensitiveDict(payload.get("headers", {}))
    response._content = payload.get("content", b"")
    response.url = payload.get("url", "")
    response.reason = payload.get("reason", "")
    response.encoding = payload.get("encoding")
    return response


def _http_request_worker(
    conn: multiprocessing.connection.Connection,
    method_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    """Run a requests call in a child process so the parent can hard-timeout it."""
    try:
        fn = getattr(requests, method_name)
        response = fn(*args, **kwargs)
        conn.send({"ok": True, "response": _serialize_response(response)})
    except Exception as exc:
        conn.send(
            {
                "ok": False,
                "exc_type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
    finally:
        conn.close()


def _terminate_process(process: Any) -> None:
    """Terminate a child process and ensure it is reaped."""
    process.terminate()
    process.join(timeout=1)
    if process.is_alive():
        process.kill()
        process.join(timeout=1)


def _wait_for_worker_result(
    process: Any,
    conn: multiprocessing.connection.Connection,
    provider: str,
    hard_timeout_seconds: float,
) -> dict[str, Any]:
    """Wait for child-process result up to a hard deadline."""
    deadline = time.monotonic() + hard_timeout_seconds
    while True:
        if conn.poll(0.1):
            return conn.recv()
        if not process.is_alive():
            if conn.poll(0):
                return conn.recv()
            raise RuntimeError(
                f"{provider} HTTP worker exited with code {process.exitcode} without returning a response"
            )
        if time.monotonic() >= deadline:
            logger.warning(
                "%s hard timeout after %.1fs waiting for HTTP response body; killing worker pid=%s",
                provider,
                hard_timeout_seconds,
                process.pid,
            )
            _terminate_process(process)
            raise requests.exceptions.Timeout(
                f"{provider} hard timeout after {hard_timeout_seconds:.1f}s"
            )


def _restore_child_exception(provider: str, payload: dict[str, Any]) -> Exception:
    """Map child-process exception payloads back into requests/native exceptions."""
    exc_type = payload.get("exc_type", "RuntimeError")
    message = payload.get("message", "")
    trace = payload.get("traceback", "")

    if exc_type in {"ConnectTimeout", "ReadTimeout", "Timeout"}:
        return requests.exceptions.Timeout(f"{provider} {message}")
    if exc_type in {"ConnectionError", "ProxyError", "SSLError"}:
        return requests.exceptions.ConnectionError(f"{provider} {message}")
    if exc_type == "HTTPError":
        return requests.HTTPError(message)
    if trace:
        return RuntimeError(f"{provider} HTTP worker failed with {exc_type}: {message}\n{trace}")
    return RuntimeError(f"{provider} HTTP worker failed with {exc_type}: {message}")


def _resolve_hard_timeout_seconds(provider: str, timeout: Any, override: float | None) -> float:
    """Choose a wall-clock timeout for a single HTTP attempt."""
    if override is not None:
        return override

    provider_env = os.getenv(f"FWMA_{provider.upper()}_HARD_TIMEOUT_SECONDS")
    if provider_env:
        return float(provider_env)

    global_env = os.getenv("FWMA_LLM_HARD_TIMEOUT_SECONDS")
    if global_env:
        return float(global_env)

    if isinstance(timeout, tuple) and len(timeout) == 2 and timeout[1] is not None:
        return max(float(timeout[1]) + 60.0, DEFAULT_HARD_TIMEOUT_SECONDS)
    if isinstance(timeout, (int, float)):
        return max(float(timeout) + 60.0, DEFAULT_HARD_TIMEOUT_SECONDS)
    return DEFAULT_HARD_TIMEOUT_SECONDS


def _invoke_http_call(
    fn: callable,
    provider: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    hard_timeout_seconds: float,
) -> requests.Response:
    """Execute an HTTP call with a real wall-clock deadline."""
    method_name = getattr(fn, "__name__", "")
    if method_name not in HTTP_METHOD_NAMES:
        return fn(*args, **kwargs)

    ctx = get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_http_request_worker,
        args=(child_conn, method_name, args, kwargs),
    )
    process.start()
    child_conn.close()

    try:
        payload = _wait_for_worker_result(process, parent_conn, provider, hard_timeout_seconds)
    finally:
        parent_conn.close()
        process.join(timeout=1)
        if process.is_alive():
            _terminate_process(process)

    if payload.get("ok"):
        return _deserialize_response(payload["response"])
    raise _restore_child_exception(provider, payload)


def _call_with_retry(
    fn: callable,
    provider: str,
    *args: Any,
    **kwargs: Any,
) -> requests.Response:
    """Execute HTTP call with exponential backoff retry on transient errors."""
    _rate_limit_wait(provider)
    hard_timeout_seconds = _resolve_hard_timeout_seconds(
        provider,
        kwargs.get("timeout"),
        kwargs.pop("hard_timeout_seconds", None),
    )
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        started_at = time.monotonic()
        try:
            response = _invoke_http_call(fn, provider, args, kwargs, hard_timeout_seconds)
            elapsed = time.monotonic() - started_at
            logger.debug(
                "%s HTTP attempt %d/%d finished with status %s in %.1fs",
                provider,
                attempt + 1,
                MAX_RETRIES + 1,
                response.status_code,
                elapsed,
            )
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
            elapsed = time.monotonic() - started_at
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                f"{provider} {type(e).__name__} after {elapsed:.1f}s, "
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
        "Connection": "close",
    }

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": safe_messages,
        "stream": False,
    }
    if system_prompt:
        payload["system"] = [{"type": "text", "text": system_prompt}]
        prefix = f"[系统指令]\n{system_prompt}\n[/系统指令]\n\n"
        for msg in safe_messages:
            if msg.get("role") == "user":
                msg["content"] = prefix + msg.get("content", "")
                break

    logger.debug(f"Calling Anthropic: {model}")
    response = _call_with_retry(requests.post, "anthropic", url, headers=headers, json=payload, timeout=(10, 300))

    data = response.json()

    if "error" in data:
        raise RuntimeError(f"Anthropic API error: {data['error']}")

    content = data.get("content", [])
    # Extract text blocks, skip tool_use blocks (new-api may inject tools)
    text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
    result = "\n".join(text_parts) if text_parts else ""
    if not result.strip():
        logger.warning(f"Anthropic returned empty/blank response. content={content!r}, data keys={list(data.keys())}")
    return result


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

    url = f"{base_url}/v1beta/models/{model}:generateContent"

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
        json=payload, timeout=(10, 300),
    )

    data = response.json()
    candidates = data.get("candidates", [])
    if not candidates:
        logger.warning(f"Gemini returned no candidates. data keys={list(data.keys())}")
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


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
        "Connection": "close",
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
    response = _call_with_retry(requests.post, provider, url, headers=headers, json=payload, timeout=(10, 300))
    data = response.json()

    if "error" in data:
        raise RuntimeError(f"API error: {data['error']}")

    choices = data.get("choices", [])
    result = choices[0].get("message", {}).get("content", "") if choices else ""
    if not result.strip():
        logger.warning(f"OpenAI returned empty/blank response. choices={choices!r}, data keys={list(data.keys())}")
    return result


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

            response = _call_with_retry(requests.post, "gemini", url, headers=headers, json=payload, timeout=(10, 300))
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
        json=payload_native, timeout=(10, 300),
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
