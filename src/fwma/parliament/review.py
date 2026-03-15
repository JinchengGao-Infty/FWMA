"""Paper review using AI Parliament debate."""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fwma.parliament.debate import Parliament
from fwma.tools.pdf_vision import extract_text_from_pdf, extract_visuals_from_pdf, format_visuals_for_context

logger = logging.getLogger(__name__)


def _clone_parliament(parliament: Parliament) -> Parliament:
    """Create a shallow Parliament copy with a fresh LLM client for one worker."""
    try:
        cloned = copy.copy(parliament)
        cloned.client = parliament.client.__class__(api_keys=dict(parliament.client.api_keys))
        return cloned
    except Exception as exc:
        logger.warning("Failed to clone Parliament for worker thread; reusing shared instance: %s", exc)
        return parliament


def review_paper(
    paper: dict,
    user_requirement: str,
    parliament: Parliament | None = None,
    pdf_path: Path | str | None = None,
    vision_model: str = "gemini/gemini-3-flash",
) -> dict:
    """Review a single paper using AI Parliament.

    Process:
    1. Extract text from PDF (if available)
    2. Extract visuals using vision model (tables, figures, formulas)
    3. Run Parliament debate on the paper
    4. Generate verdict with score and recommendation

    Args:
        paper: Paper metadata dict (title, authors, abstract, etc.)
        user_requirement: Research requirement for evaluation context
        parliament: Parliament instance (creates default if None)
        pdf_path: Path to PDF file (optional, uses abstract if not available)
        vision_model: Model for PDF visual extraction

    Returns:
        Dict with paper_info, debate_history, final_verdict
    """
    if parliament is None:
        parliament = Parliament()

    # Build paper context
    paper_text = f"标题: {paper.get('title', 'Unknown')}\n"
    paper_text += f"作者: {', '.join(paper.get('authors', []))}\n"
    paper_text += f"年份: {paper.get('year', 'Unknown')}\n"
    paper_text += f"摘要: {paper.get('abstract', 'No abstract')}\n"

    # Extract PDF content if available
    if pdf_path and Path(pdf_path).exists():
        try:
            pdf_full_text = extract_text_from_pdf(str(pdf_path))
            if pdf_full_text:
                paper_text += f"\n--- 论文全文 ---\n{pdf_full_text}\n"

            # Extract visuals (tables, figures, formulas)
            try:
                visuals = extract_visuals_from_pdf(str(pdf_path), model=vision_model)
                if visuals:
                    visuals_text = format_visuals_for_context(visuals)
                    paper_text += f"\n--- 图表与公式 ---\n{visuals_text}\n"
            except Exception as e:
                logger.warning(f"Visual extraction failed for {pdf_path}: {e}")
        except Exception as e:
            logger.warning(f"PDF text extraction failed for {pdf_path}: {e}")

    # Run debate
    result = parliament.hold_debate(paper_text, user_requirement)

    return {
        "paper_info": {
            "title": paper.get("title"),
            "authors": paper.get("authors", []),
            "year": paper.get("year"),
            "doi": paper.get("doi"),
            "url": paper.get("url"),
        },
        "debate_history": result.get("debate_history", []),
        "final_verdict": result.get("final_verdict", {}),
    }


def review_batch(
    papers: list[dict],
    user_requirement: str,
    parliament: Parliament | None = None,
    pdf_dir: Path | str | None = None,
    reviews_dir: Path | str | None = None,
    vision_model: str = "gemini/gemini-3-flash",
    max_papers: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    concurrency: int = 3,
) -> list[dict]:
    """Review multiple papers with resume support.

    Args:
        papers: List of paper metadata dicts
        user_requirement: Research requirement
        parliament: Parliament instance
        pdf_dir: Directory containing downloaded PDFs
        reviews_dir: Directory to save individual review JSONs (for resume)
        vision_model: Model for PDF visual extraction
        max_papers: Maximum papers to review
        on_progress: Callback(current, total) for progress reporting
        concurrency: Number of concurrent review threads (default 3)

    Returns:
        List of review result dicts
    """
    if parliament is None:
        parliament = Parliament()

    if reviews_dir:
        reviews_dir = Path(reviews_dir)
        reviews_dir.mkdir(parents=True, exist_ok=True)

    if pdf_dir:
        pdf_dir = Path(pdf_dir)

    papers_to_review = papers[:max_papers] if max_papers else papers

    # Separate already-reviewed (resume) from pending
    resumed_results: dict[int, dict] = {}
    pending: list[tuple[int, dict]] = []

    for i, paper in enumerate(papers_to_review):
        title = paper.get("title", "unknown")
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)[:80]

        if reviews_dir:
            review_path = reviews_dir / f"{safe_title}.json"
            if review_path.exists():
                logger.info(f"[{i + 1}/{len(papers_to_review)}] Skipping (already reviewed): {title[:60]}")
                try:
                    with open(review_path, encoding="utf-8") as f:
                        resumed_results[i] = json.load(f)
                    if on_progress:
                        on_progress(i + 1, len(papers_to_review))
                    continue
                except Exception:
                    pass  # Re-review if JSON is corrupted

        pending.append((i, paper))

    def _find_pdf(paper: dict, safe_title: str) -> Path | None:
        if not pdf_dir:
            return None
        pdf_path = paper.get("pdf_path")
        if pdf_path:
            pdf_path = Path(pdf_path)
            if not pdf_path.exists():
                pdf_path = pdf_dir / pdf_path.name
        if not pdf_path or not pdf_path.exists():
            candidate = pdf_dir / f"{safe_title}.pdf"
            if candidate.exists():
                return candidate
            return None
        return pdf_path

    def _review_one(idx: int, paper: dict) -> tuple[int, dict]:
        title = paper.get("title", "unknown")
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)[:80]
        logger.info(f"[{idx + 1}/{len(papers_to_review)}] Reviewing: {title[:60]}")

        try:
            pdf_path = _find_pdf(paper, safe_title)
            worker_parliament = parliament if concurrency <= 1 else _clone_parliament(parliament)
            result = review_paper(
                paper=paper,
                user_requirement=user_requirement,
                parliament=worker_parliament,
                pdf_path=pdf_path,
                vision_model=vision_model,
            )
            if reviews_dir:
                with open(reviews_dir / f"{safe_title}.json", "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Review failed for '{title[:60]}': {e}")
            result = {
                "paper_info": {"title": title, "error": str(e)},
                "debate_history": [],
                "final_verdict": {"error": str(e)},
            }
        return idx, result

    # Run reviews concurrently
    concurrent_results: dict[int, dict] = {}
    completed_count = len(resumed_results)

    if concurrency <= 1:
        for idx, paper in pending:
            idx, result = _review_one(idx, paper)
            concurrent_results[idx] = result
            completed_count += 1
            if on_progress:
                on_progress(completed_count, len(papers_to_review))
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(_review_one, idx, paper): idx for idx, paper in pending}
            for future in as_completed(futures):
                idx, result = future.result()
                concurrent_results[idx] = result
                completed_count += 1
                if on_progress:
                    on_progress(completed_count, len(papers_to_review))

    # Merge results in original order
    all_results: dict[int, dict] = {**resumed_results, **concurrent_results}
    return [all_results[i] for i in sorted(all_results)]
