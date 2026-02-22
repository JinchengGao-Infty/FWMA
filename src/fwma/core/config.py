"""Configuration management — env vars + TOML + defaults."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ModelsConfig(BaseModel):
    """LLM model assignments for each role."""

    screener: str = "gemini/gemini-2.5-flash"
    chair: str = "gemini/gemini-2.5-pro"
    member1: str = "anthropic/claude-sonnet-4"
    member2: str = "openai/gpt-4o"


class FWMAConfig(BaseModel):
    """Global FWMA configuration."""

    # API keys (from env)
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Model assignments
    models: ModelsConfig = Field(default_factory=ModelsConfig)

    # Defaults
    language: str = "zh"
    openalex_mailto: str = ""
    runs_root: str = "./runs"

    @classmethod
    def load(cls) -> "FWMAConfig":
        """Load config from env vars + ~/.config/fwma/config.toml."""
        config_data: dict[str, Any] = {}

        # 1. Try loading TOML config
        config_path = Path.home() / ".config" / "fwma" / "config.toml"
        if config_path.exists():
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib  # type: ignore[no-redef]
            with open(config_path, "rb") as f:
                toml_data = tomllib.load(f)
            if "models" in toml_data:
                config_data["models"] = ModelsConfig(**toml_data["models"])
            for key in ("language", "openalex_mailto", "runs_root"):
                if key in toml_data.get("defaults", {}):
                    config_data[key] = toml_data["defaults"][key]

        # 2. Override with env vars
        config_data["gemini_api_key"] = os.getenv("GEMINI_API_KEY", "")
        config_data["anthropic_api_key"] = os.getenv("ANTHROPIC_API_KEY", "")
        config_data["openai_api_key"] = os.getenv("OPENAI_API_KEY", "")

        if mailto := os.getenv("FWMA_OPENALEX_MAILTO"):
            config_data["openalex_mailto"] = mailto
        if runs_root := os.getenv("FWMA_RUNS_ROOT"):
            config_data["runs_root"] = runs_root

        return cls(**config_data)
