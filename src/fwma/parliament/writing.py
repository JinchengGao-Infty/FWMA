"""Writing review using AI Parliament debate.

Reviews a manuscript's writing quality using multi-agent debate,
providing detailed improvement suggestions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fwma.llm.client import LLMClient
from fwma.parliament.debate import Parliament
from fwma.tools.pdf_vision import extract_text_from_pdf, extract_visuals_from_pdf, format_visuals_for_context
from fwma.prompts.zh import WritingParliamentPrompts

logger = logging.getLogger(__name__)


def load_reference_context(reviews_dir: Path | str | None = None, report_path: Path | str | None = None) -> str:
    """Load highly applicable reviews and research report as reference context."""
    context_parts = []

    if reviews_dir:
        reviews_dir = Path(reviews_dir)
        if reviews_dir.exists():
            review_files = sorted(reviews_dir.glob("*_review.json"))
            highly_applicable = []
            for rf in review_files:
                try:
                    with open(rf, "r", encoding="utf-8") as f:
                        review = json.load(f)
                    verdict = review.get("final_verdict", {})
                    if verdict.get("recommendation") == "highly_applicable":
                        paper_info = review.get("paper_info", {})
                        highly_applicable.append(
                            {
                                "title": paper_info.get("title", "Unknown"),
                                "authors": paper_info.get("authors", []),
                                "year": paper_info.get("year", ""),
                                "venue": paper_info.get("venue", ""),
                                "verdict_summary": verdict.get("content", "")[:500],
                            }
                        )
                except Exception as e:
                    logger.warning(f"Failed to load review {rf}: {e}")

            if highly_applicable:
                context_parts.append("=== 高度相关论文评审摘要 ===")
                for i, paper in enumerate(highly_applicable, 1):
                    context_parts.append(f"\n--- 论文 {i}: {paper['title']} ---")
                    context_parts.append(f"作者: {', '.join(paper['authors'][:3])}")
                    context_parts.append(f"年份: {paper['year']}, 发表于: {paper['venue']}")
                    context_parts.append(f"评审摘要: {paper['verdict_summary']}")

    if report_path:
        report_path = Path(report_path)
        if report_path.exists():
            report_content = report_path.read_text(encoding="utf-8")
            context_parts.append("\n=== 研究综述报告 ===")
            context_parts.append(report_content[:5000])

    return "\n".join(context_parts) if context_parts else ""


def generate_writing_report(
    debate_history: list[dict],
    final_verdict: dict,
    manuscript_text: str,
    target_venue: str | None = None,
    reference_context: str | None = None,
    model: str = "gemini/gemini-2.5-pro",
    output_path: Path | str | None = None,
) -> str:
    """Generate detailed writing improvement report from debate results."""
    client = LLMClient()

    prompt = WritingParliamentPrompts.get_writing_report_prompt(
        debate_history=debate_history,
        final_verdict=final_verdict,
        target_venue=target_venue or "top-tier venue",
        reference_context=reference_context or "",
    )

    messages = [{"role": "user", "content": prompt}]
    report = client.call(model=model, messages=messages)

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        logger.info(f"Writing report saved to {output_path}")

    return report


def review_writing(
    manuscript_path: Path | str,
    target_venue: str | None = None,
    user_notes: str | None = None,
    parliament: Parliament | None = None,
    max_rounds: int = 3,
    reference_context: str | None = None,
    generate_report: bool = True,
    report_model: str = "gemini/gemini-2.5-pro",
    vision_model: str = "gemini/gemini-2.5-flash",
    output_dir: Path | str | None = None,
) -> dict:
    """Review a manuscript's writing quality using AI Parliament.

    Returns dict with verdict, debate_log, and optionally a detailed report.
    """
    manuscript_path = Path(manuscript_path)
    logger.info(f"Starting writing review for {manuscript_path.name}")

    # Extract PDF content
    text = extract_text_from_pdf(manuscript_path)
    logger.info(f"Extracted {len(text)} chars of text")

    # Extract visuals
    try:
        visuals = extract_visuals_from_pdf(manuscript_path, model=vision_model)
        visuals_context = format_visuals_for_context(visuals)
        paper_text = f"{text}\n\n{visuals_context}" if visuals_context else text
        logger.info(f"Extracted {len(visuals)} visual elements")
    except Exception as e:
        logger.warning(f"Visual extraction failed: {e}, using text only")
        paper_text = text

    # Build debate context
    context_parts = [paper_text]
    if target_venue:
        context_parts.append(f"\n目标投稿期刊/会议: {target_venue}")
    if user_notes:
        context_parts.append(f"\n作者备注: {user_notes}")
    if reference_context:
        context_parts.append(f"\n参考文献评审上下文:\n{reference_context}")

    debate_context = "\n".join(context_parts)

    # Create parliament with writing-specific prompts
    if parliament is None:
        parliament = Parliament(
            chair_prompts={
                "system": WritingParliamentPrompts.WRITING_CHAIR_SYSTEM_PROMPT,
            },
            member1_prompts={
                "system": WritingParliamentPrompts.WRITING_REVIEWER1_SYSTEM_PROMPT,
                "role": "技术审稿人",
            },
            member2_prompts={
                "system": WritingParliamentPrompts.WRITING_REVIEWER2_SYSTEM_PROMPT,
                "role": "写作审稿人",
            },
        )

    # Run debate
    writing_requirement = "请对这篇论文的写作质量进行全面评审，包括结构、逻辑、表达、技术准确性等方面。"
    result = parliament.hold_debate(
        paper_text=debate_context,
        user_requirement=writing_requirement,
        max_rounds=max_rounds,
    )

    # Generate detailed report if requested
    if generate_report:
        try:
            report = generate_writing_report(
                debate_history=result.get("debate_history", []),
                final_verdict=result.get("final_verdict", {}),
                manuscript_text=paper_text,
                target_venue=target_venue,
                reference_context=reference_context,
                model=report_model,
            )
            result["writing_report"] = report

            if output_dir:
                output_dir = Path(output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                report_path = output_dir / f"{manuscript_path.stem}_writing_report.md"
                report_path.write_text(report, encoding="utf-8")
                logger.info(f"Writing report saved to {report_path}")
        except Exception as e:
            logger.error(f"Failed to generate writing report: {e}")

    # Save result JSON
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        result_path = output_dir / f"{manuscript_path.stem}_writing_review.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"Writing review saved to {result_path}")

    return result
