"""Configuration management — env vars + TOML + defaults."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ModelsConfig(BaseModel):
    """LLM model assignments for each role."""

    screener: str = "openai/gpt-5.4"
    chair: str = "gemini/gemini-3.1-pro-preview"
    member1: str = "anthropic/claude-opus-4-6"
    member2: str = "openai/gpt-5.4"
    report: str = "gemini/gemini-3.1-pro-preview"
    writing_review: str = "anthropic/claude-opus-4-6"
    citation_check: str = "gemini/gemini-3-flash"
    pdf_vision: str = "gemini/gemini-3-flash"


class FWMAConfig(BaseModel):
    """Global FWMA configuration."""

    # API keys (from env)
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Base URLs (empty = use provider defaults)
    anthropic_base_url: str = ""
    openai_base_url: str = ""
    gemini_base_url: str = ""
    gemini_openai_base_url: str = ""

    # Model assignments
    models: ModelsConfig = Field(default_factory=ModelsConfig)

    # Defaults
    language: str = "zh"
    openalex_mailto: str = ""
    runs_root: str = "./runs"

    def validate_model_credentials(self) -> None:
        provider_to_key = {
            "gemini": self.gemini_api_key,
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
        }
        models = [
            self.models.screener,
            self.models.chair,
            self.models.member1,
            self.models.member2,
        ]
        missing: set[str] = set()
        for model in models:
            provider = model.split("/", 1)[0].strip().lower() if "/" in model else ""
            if provider in provider_to_key and not provider_to_key[provider]:
                missing.add(provider)
        if missing:
            missing_env = {
                "gemini": "GEMINI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
            }
            required = ", ".join(sorted(missing_env[p] for p in missing))
            raise ValueError(f"Missing API keys for configured models. Set: {required}")

    @classmethod
    def load(cls) -> FWMAConfig:
        """Load config from env vars + ~/.config/fwma/config.toml."""
        config_data: dict[str, Any] = {}

        # 1. Try loading TOML config
        config_path = Path.home() / ".config" / "fwma" / "config.toml"
        if config_path.exists():
            try:
                toml_module = importlib.import_module("tomllib")
            except ModuleNotFoundError:
                toml_module = importlib.import_module("tomli")
            with open(config_path, "rb") as f:
                toml_data = toml_module.load(f)
            if "models" in toml_data:
                config_data["models"] = ModelsConfig(**toml_data["models"])
            for key in ("language", "openalex_mailto", "runs_root"):
                if key in toml_data.get("defaults", {}):
                    config_data[key] = toml_data["defaults"][key]

        # 2. Override with env vars
        config_data["gemini_api_key"] = os.getenv("GEMINI_API_KEY", "")
        config_data["anthropic_api_key"] = os.getenv("ANTHROPIC_API_KEY", "")
        config_data["openai_api_key"] = os.getenv("OPENAI_API_KEY", "")

        config_data["anthropic_base_url"] = os.getenv("ANTHROPIC_BASE_URL", "")
        config_data["openai_base_url"] = os.getenv("OPENAI_BASE_URL", "")
        config_data["gemini_base_url"] = os.getenv("GEMINI_BASE_URL", "")
        config_data["gemini_openai_base_url"] = os.getenv("GEMINI_OPENAI_BASE_URL", "")

        if mailto := os.getenv("FWMA_OPENALEX_MAILTO"):
            config_data["openalex_mailto"] = mailto
        if runs_root := os.getenv("FWMA_RUNS_ROOT"):
            config_data["runs_root"] = runs_root

        return cls(**config_data)
