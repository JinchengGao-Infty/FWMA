"""Citation reasonability checker.

Checks whether citations in a LaTeX manuscript are used
appropriately by cross-referencing with the cited papers.
"""

from __future__ import annotations

from pathlib import Path


def check_citations(
    bib_index: dict[str, dict],
    manuscript: str | None = None,
    manuscript_path: Path | str | None = None,
    model: str = "gemini/gemini-2.5-flash",
) -> dict:
    """Check citation reasonability in a manuscript.

    Args:
        bib_index: Dict mapping citation keys to {title, pdf} info
        manuscript: LaTeX manuscript content (string)
        manuscript_path: Path to .tex file (alternative to manuscript)
        model: Vision model for reading cited PDFs

    Returns dict with per-citation assessments and overall score.
    """
    raise NotImplementedError("Citation checking not yet implemented")


def parse_bib_file(bib_path: Path | str) -> dict[str, dict]:
    """Parse .bib file into bib_index format."""
    raise NotImplementedError
