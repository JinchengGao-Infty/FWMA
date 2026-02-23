"""Research report generator."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fwma.llm.client import LLMClient
from fwma.prompts.roles.report import SYSTEM_PROMPT as REPORT_PROMPT
from fwma.prompts.zh import Step5Prompts

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate research summary reports from review results."""

    def __init__(self, model: str = "gemini/gemini-2.5-pro"):
        self.client = LLMClient()
        self.model = model

    def generate(self, reviews: list[dict], requirement: str, format: str = "markdown") -> str:
        """Generate a research report from all reviews.

        Args:
            reviews: List of review result dicts (with paper_info, final_verdict).
            requirement: Original research requirement.
            format: Output format ('markdown' or 'json').
        """
        logger.info(f"Generating report from {len(reviews)} reviews")

        # Sort reviews by recommendation
        sorted_reviews = sorted(
            reviews,
            key=lambda r: {
                "highly_applicable": 0,
                "moderately_applicable": 1,
                "not_applicable": 2,
            }.get(r.get("final_verdict", {}).get("recommendation", ""), 3),
        )

        # Build review summaries for the prompt
        review_summaries = []
        for review in sorted_reviews:
            paper_info = review.get("paper_info", {})
            verdict = review.get("final_verdict", {})
            review_summaries.append(
                {
                    "title": paper_info.get("title", "Unknown"),
                    "authors": paper_info.get("authors", []),
                    "year": paper_info.get("year", ""),
                    "venue": paper_info.get("venue", ""),
                    "recommendation": verdict.get("recommendation", "unknown"),
                    "score": verdict.get("score", 0),
                    "key_points": verdict.get("key_points", []),
                    "application_ideas": verdict.get("application_ideas", []),
                    "content": verdict.get("content", ""),
                }
            )

        prompt = Step5Prompts.get_report_prompt(
            all_reviews=review_summaries,
            user_requirement=requirement,
            num_papers=len(reviews),
        )

        messages = [{"role": "user", "content": prompt}]
        report = self.client.call(model=self.model, messages=messages, system_prompt=REPORT_PROMPT)

        if format == "json":
            return json.dumps(
                {
                    "requirement": requirement,
                    "total_papers": len(reviews),
                    "report": report,
                    "reviews": review_summaries,
                },
                ensure_ascii=False,
                indent=2,
            )

        return report

    def save(self, content: str, output_path: Path | str) -> Path:
        """Save report to file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        logger.info(f"Report saved to {output_path}")
        return output_path
