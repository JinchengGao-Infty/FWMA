"""FWMA MCP Server — AI Parliament-driven literature review for AI agents.

Start with: fwma mcp
Or: uvx --from fwma fwma-mcp
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

try:
    from fastmcp import FastMCP  # pyright: ignore[reportMissingImports]
except ImportError:
    raise ImportError("MCP support requires fastmcp. Install with: pip install fwma[mcp]")

from fwma.core.service import FWMAService

_SERVICE: FWMAService | None = None


@asynccontextmanager
async def _lifespan(_: Any):
    global _SERVICE
    _SERVICE = FWMAService()
    try:
        yield {"service": _SERVICE}
    finally:
        _SERVICE = None


def _get_service(ctx: Any | None = None) -> FWMAService:
    if ctx is not None:
        request_context = getattr(ctx, "request_context", None)
        lifespan_context = getattr(request_context, "lifespan_context", None)
        if isinstance(lifespan_context, dict):
            service = lifespan_context.get("service")
            if isinstance(service, FWMAService):
                return service
        service = getattr(lifespan_context, "service", None)
        if isinstance(service, FWMAService):
            return service

    global _SERVICE
    if _SERVICE is None:
        _SERVICE = FWMAService()
    return _SERVICE


mcp = FastMCP("fwma", description="AI Parliament-driven systematic literature review", lifespan=_lifespan)


@mcp.tool()
async def suggest_sources(requirement: str, model: str | None = None) -> dict:
    """Generate AI-powered search strategy from a research requirement.

    Returns suggested sources configuration for OpenAlex, arXiv, and OpenReview.
    """
    return _get_service().suggest_sources(requirement=requirement, model=model)


@mcp.tool()
async def run_create(
    requirement: str,
    sources: list[dict],
    name: str | None = None,
    run_id: str | None = None,
) -> dict:
    """Create a new research run with requirement and source configuration.

    Returns run_id and initial status.
    """
    return _get_service().create_run(
        requirement=requirement,
        sources=sources,
        name=name,
        run_id=run_id,
    )


@mcp.tool()
async def crawl(run_id: str, timeout_s: int = 600) -> dict:
    """Crawl papers from configured sources (OpenAlex, arXiv, OpenReview).

    Returns crawl statistics and paper count.
    """
    _ = timeout_s
    return _get_service().crawl(run_id=run_id)


@mcp.tool()
async def screen(run_id: str, threshold: str = "high_medium") -> dict:
    """Screen papers for relevance using AI.

    Threshold options: high_only, high_medium, all_selected.
    Returns screening statistics.
    """
    return _get_service().screen(run_id=run_id, threshold=threshold)


@mcp.tool()
async def download(run_id: str, concurrency: int = 8, ctx: Any | None = None) -> dict:
    """Download PDFs for screened papers. Long-running operation with progress reporting.

    Uses multi-strategy fallback: direct URL → Unpaywall → DOI redirect → browser.
    """
    service = _get_service(ctx)
    job_id = service.download_async(run_id=run_id, concurrency=concurrency)
    return {"run_id": run_id, "job_id": job_id, "status": service.get_job_status(job_id)}


@mcp.tool()
async def review(run_id: str, max_rounds: int = 5, ctx: Any | None = None) -> dict:
    """Review papers with AI Parliament debate. Long-running operation.

    Each paper goes through structured multi-agent debate:
    Chair opens → Members argue → Vote check → Final verdict with score.
    """
    service = _get_service(ctx)
    job_id = service.review_async(run_id=run_id, max_rounds=max_rounds)
    return {"run_id": run_id, "job_id": job_id, "status": service.get_job_status(job_id)}


@mcp.tool()
async def report(run_id: str, format: str = "markdown") -> dict:
    """Generate research summary report from all reviews.

    Format options: markdown, json, both.
    """
    service = _get_service()
    job_id = service.report_async(run_id=run_id, format=format)
    return {"run_id": run_id, "job_id": job_id, "status": service.get_job_status(job_id)}


@mcp.tool()
async def writing_review(manuscript: str, max_rounds: int = 3, target_venue: str | None = None) -> dict:
    """Review manuscript writing quality using AI Parliament debate.

    Returns verdict, debate log, and detailed improvement suggestions.
    """
    _ = target_venue
    service = _get_service()
    job_id = service.writing_review_async(manuscript=manuscript, max_rounds=max_rounds)
    return {"job_id": job_id, "status": service.get_job_status(job_id)}


@mcp.tool()
async def parliament_debate(topic: str, context: str | None = None, max_rounds: int = 5) -> dict:
    """Run a standalone AI Parliament debate on any topic.

    Useful for general-purpose multi-agent evaluation and discussion.
    """
    return _get_service().parliament_debate(topic=topic, context=context, max_rounds=max_rounds)


@mcp.tool()
async def pdf_vision(pdf_path: str) -> dict:
    """Extract tables, figures, and formulas from PDF using vision model."""
    return _get_service().pdf_vision(pdf_path=pdf_path)


@mcp.tool()
async def citation_check(bib_index: dict, manuscript: str | None = None) -> dict:
    """Check citation reasonability in a manuscript against cited papers."""
    typed_bib_index: dict[str, dict[Any, Any]] | str = bib_index
    return _get_service().citation_check(bib_index=typed_bib_index, manuscript=manuscript)


@mcp.tool()
async def run_status(run_id: str) -> dict:
    """Get status and available artifacts for a research run."""
    return _get_service().run_status(run_id=run_id)


@mcp.tool()
async def artifact_read(run_id: str, path: str) -> dict:
    """Read a text artifact (JSON, Markdown, log) from a research run."""
    content = _get_service().read_artifact(run_id=run_id, path=path)
    return {"run_id": run_id, "path": path, "content": content}


def main():
    """Entry point for fwma-mcp command."""
    mcp.run()
