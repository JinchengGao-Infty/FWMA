"""Unified LLM client — thin abstraction over multiple providers."""

from __future__ import annotations

import logging
import os
from typing import Any

from fwma.llm.providers import (
    PROVIDERS,
    call_anthropic,
    call_gemini_native,
    call_gemini_structured,
    call_openai_format,
    get_api_key,
    get_base_url,
)

logger = logging.getLogger(__name__)


class LLMClient:
    """Call any supported LLM with a unified interface.

    Model string format: "provider/model-name"
    Examples:
        - "gemini/gemini-2.5-flash"
        - "anthropic/claude-sonnet-4"
        - "openai/gpt-4o"

    Legacy short names also supported for backward compatibility:
        - "claude" -> calls Anthropic
        - "gpt" -> calls OpenAI
        - "gemini" -> calls Gemini native
    """

    # Legacy model name mapping
    LEGACY_MODELS = {
        "claude": ("anthropic", "claude-sonnet-4"),
        "gpt": ("openai", "gpt-4o"),
        "gemini": ("gemini", "gemini-2.5-flash"),
    }

    def __init__(self, api_keys: dict[str, str] | None = None) -> None:
        self.api_keys = api_keys or {}

    def _resolve_model(self, model: str) -> tuple[str, str]:
        """Parse 'provider/model-name' or legacy short name into (provider, model)."""
        # Legacy short names
        if model in self.LEGACY_MODELS:
            return self.LEGACY_MODELS[model]

        if "/" in model:
            provider, model_name = model.split("/", 1)
            return provider, model_name

        # Default to openai-compatible
        return "openai", model

    def _get_key(self, provider: str) -> str:
        """Get API key from instance config or environment."""
        if provider in self.api_keys:
            return self.api_keys[provider]
        return get_api_key(provider)

    def call(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        system_prompt: str | None = None,
        max_tokens: int = 8192,
        **kwargs: Any,
    ) -> str:
        """Call an LLM and return the response text.

        Args:
            model: Provider/model string (e.g. "gemini/gemini-2.5-flash")
                   or legacy name ("claude", "gpt", "gemini")
            messages: Chat messages in OpenAI format
            system_prompt: Optional system prompt
            max_tokens: Maximum response tokens
        """
        provider, model_name = self._resolve_model(model)
        api_key = self._get_key(provider)
        base_url = get_base_url(provider)

        logger.info(f"LLM call: {provider}/{model_name}")

        if provider == "anthropic":
            return call_anthropic(
                model=model_name,
                messages=messages,
                api_key=api_key,
                base_url=base_url,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                **kwargs,
            )
        elif provider == "gemini":
            return call_gemini_native(
                model=model_name,
                messages=messages,
                api_key=api_key,
                base_url=base_url,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                **kwargs,
            )
        elif provider == "openai":
            return call_openai_format(
                model=model_name,
                messages=messages,
                api_key=api_key,
                base_url=base_url,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                provider="openai",
                **kwargs,
            )
        else:
            # Treat as OpenAI-compatible
            return call_openai_format(
                model=model_name,
                messages=messages,
                api_key=api_key,
                base_url=base_url,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                provider=provider,
                **kwargs,
            )

    def call_structured(
        self,
        model: str,
        messages: list[dict[str, str]],
        response_format: Any,
        *,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Call an LLM and parse response into a Pydantic model.

        Uses Gemini structured output when provider is gemini,
        otherwise falls back to JSON mode + parsing.
        """
        provider, model_name = self._resolve_model(model)
        api_key = self._get_key(provider)

        if provider == "gemini":
            return call_gemini_structured(
                model=model_name,
                messages=messages,
                response_format=response_format,
                api_key=api_key,
                system_prompt=system_prompt,
                **kwargs,
            )
        else:
            # For non-Gemini: call normally with JSON instruction, then parse
            json_instruction = (
                f"\n\nRespond with valid JSON matching this schema: "
                f"{response_format.model_json_schema() if hasattr(response_format, 'model_json_schema') else '{}'}"
            )
            augmented_messages = list(messages)
            if augmented_messages:
                last = augmented_messages[-1].copy()
                last["content"] = last.get("content", "") + json_instruction
                augmented_messages[-1] = last

            raw = self.call(
                model,
                augmented_messages,
                system_prompt=system_prompt,
                **kwargs,
            )

            from fwma.llm.providers import _parse_structured

            return _parse_structured(raw, response_format)
