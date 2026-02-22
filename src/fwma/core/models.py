"""Pydantic data models for FWMA."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Paper(BaseModel):
    """Normalized paper metadata from any source."""

    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    abstract: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    pdf_path: str | None = None
    source: str | None = None  # openalex / arxiv / openreview
    venue: str | None = None
    citation_count: int | None = None
    extra: dict = Field(default_factory=dict)


class SourceConfig(BaseModel):
    """Single search source configuration."""

    type: str  # openalex / arxiv / openreview
    query: dict = Field(default_factory=dict)


class ScreenResult(BaseModel):
    """Screening result for a single paper."""

    paper: Paper
    relevance: str  # high / medium / low
    reason: str = ""


class ReviewResult(BaseModel):
    """AI Parliament review result for a single paper."""

    paper: Paper
    verdict: str = ""  # highly_applicable / moderately_applicable / not_applicable
    score: float = 0.0
    key_points: list[str] = Field(default_factory=list)
    application_ideas: list[str] = Field(default_factory=list)
    debate_log: list[dict] = Field(default_factory=list)


class RunConfig(BaseModel):
    """Per-research-run configuration (from research.toml)."""

    name: str = "unnamed"
    requirement: str = ""
    sources: list[SourceConfig] = Field(default_factory=list)
    max_papers_crawl: int = 500
    oa_only: bool = False
