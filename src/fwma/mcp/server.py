"""FWMA MCP Server — AI Parliament-driven literature review for AI agents.

Start with: fwma mcp
Or: uvx --from fwma fwma-mcp
"""

from __future__ import annotations

try:
    from fastmcp import FastMCP, Context
except ImportError:
    raise ImportError("MCP support requires fastmcp. Install with: pip install fwma[mcp]")

mcp = FastMCP("fwma", description="AI Parliament-driven systematic literature review")


@mcp.tool()
async def suggest_sources(requirement: str, model: str | None = None) -> dict:
    """Generate AI-powered search strategy from a research requirement.

    Returns suggested sources configuration for OpenAlex, arXiv, and OpenReview.
    """
    raise NotImplementedError("suggest_sources not yet implemented")


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
    raise NotImplementedError("run_create not yet implemented")


@mcp.tool()
async def crawl(run_id: str, timeout_s: int = 600) -> dict:
    """Crawl papers from configured sources (OpenAlex, arXiv, OpenReview).

    Returns crawl statistics and paper count.
    """
    raise NotImplementedError("crawl not yet implemented")


@mcp.tool()
async def screen(run_id: str, threshold: str = "high_medium") -> dict:
    """Screen papers for relevance using AI.

    Threshold options: high_only, high_medium, all_selected.
    Returns screening statistics.
    """
    raise NotImplementedError("screen not yet implemented")


@mcp.tool()
async def download(run_id: str, concurrency: int = 8, ctx: Context | None = None) -> dict:
    """Download PDFs for screened papers. Long-running operation with progress reporting.

    Uses multi-strategy fallback: direct URL → Unpaywall → DOI redirect → browser.
    """
    raise NotImplementedError("download not yet implemented")


@mcp.tool()
async def review(run_id: str, max_rounds: int = 5, ctx: Context | None = None) -> dict:
    """Review papers with AI Parliament debate. Long-running operation.

    Each paper goes through structured multi-agent debate:
    Chair opens → Members argue → Vote check → Final verdict with score.
    """
    raise NotImplementedError("review not yet implemented")


@mcp.tool()
async def report(run_id: str, format: str = "markdown") -> dict:
    """Generate research summary report from all reviews.

    Format options: markdown, json, both.
    """
    raise NotImplementedError("report not yet implemented")


@mcp.tool()
async def writing_review(manuscript: str, max_rounds: int = 3, target_venue: str | None = None) -> dict:
    """Review manuscript writing quality using AI Parliament debate.

    Returns verdict, debate log, and detailed improvement suggestions.
    """
    raise NotImplementedError("writing_review not yet implemented")


@mcp.tool()
async def parliament_debate(topic: str, context: str | None = None, max_rounds: int = 5) -> dict:
    """Run a standalone AI Parliament debate on any topic.

    Useful for general-purpose multi-agent evaluation and discussion.
    """
    raise NotImplementedError("parliament_debate not yet implemented")


@mcp.tool()
async def pdf_vision(pdf_path: str) -> dict:
    """Extract tables, figures, and formulas from PDF using vision model."""
    raise NotImplementedError("pdf_vision not yet implemented")


@mcp.tool()
async def citation_check(bib_index: dict, manuscript: str | None = None) -> dict:
    """Check citation reasonability in a manuscript against cited papers."""
    raise NotImplementedError("citation_check not yet implemented")


@mcp.tool()
async def run_status(run_id: str) -> dict:
    """Get status and available artifacts for a research run."""
    raise NotImplementedError("run_status not yet implemented")


@mcp.tool()
async def artifact_read(run_id: str, path: str) -> dict:
    """Read a text artifact (JSON, Markdown, log) from a research run."""
    raise NotImplementedError("artifact_read not yet implemented")


def main():
    """Entry point for fwma-mcp command."""
    mcp.run()
