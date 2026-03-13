"""AI-powered paper relevance screening."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from fwma.core.utils import parse_json_response
from fwma.llm.client import LLMClient
from fwma.prompts.roles.screener import SYSTEM_PROMPT as SCREENER_PROMPT
from fwma.prompts.zh import Step2Prompts

logger = logging.getLogger(__name__)


class Screener:
    """Screen papers for relevance using LLM."""

    def __init__(self, model: str = "openai/gpt-4o"):
        self.client = LLMClient()
        self.model = model

    def screen(
        self,
        papers: list[dict],
        requirement: str,
        threshold: str = "high_medium",
        batch_size: int = 50,
        existing_results: list[dict] | None = None,
        concurrency: int = 3,
    ) -> list[dict]:
        """Screen papers for relevance. Returns filtered results.

        Args:
            papers: List of paper dicts with title, abstract, etc.
            requirement: Research requirement text.
            threshold: 'high_only', 'high_medium', or 'all_selected'.
            batch_size: Number of papers per LLM call.
            existing_results: Previously screened results for resume.
            concurrency: Number of batches to screen in parallel.
        """
        if existing_results:
            screened_ids = {p.get("id") for p in existing_results}
            papers = [p for p in papers if p.get("id") not in screened_ids]
            logger.info(f"Resume: skipping {len(screened_ids)} already screened papers")

        all_selected = list(existing_results or [])

        # Prepare batches
        batches = []
        for i in range(0, len(papers), batch_size):
            batch = papers[i : i + batch_size]
            for idx, paper in enumerate(batch):
                if not paper.get("id"):
                    paper["_screen_id"] = str(i + idx)
            batches.append((i // batch_size + 1, batch))

        def _screen_batch(batch_num: int, batch: list[dict]) -> list[dict]:
            logger.info(f"Screening batch {batch_num}/{len(batches)} ({len(batch)} papers)")
            prompt = Step2Prompts.get_screening_prompt(batch, requirement)
            response = self.client.call(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                system_prompt=SCREENER_PROMPT,
            )
            result = parse_json_response(response)
            if isinstance(result, dict):
                selected = result.get("selected_papers", [])
            elif isinstance(result, list):
                selected = result
            else:
                logger.warning(f"Unexpected screening response format: {type(result)}")
                return []

            batch_results = []
            for sel in selected:
                paper_id = sel.get("id") or sel.get("paper_id") or sel.get("index")
                relevance = sel.get("relevance", "medium")
                if threshold == "high_only" and relevance != "high":
                    continue
                if threshold == "high_medium" and relevance not in ("high", "medium"):
                    continue
                matching = [p for p in batch if str(p.get("id") or p.get("_screen_id", "")) == str(paper_id)]
                if matching:
                    paper_info = matching[0].copy()
                    paper_info.pop("_screen_id", None)
                    paper_info["relevance"] = relevance
                    paper_info["screening_reason"] = sel.get("reason", "")
                    batch_results.append({"paper": paper_info, "relevance": relevance, "reason": sel.get("reason", "")})
                else:
                    logger.debug(f"No match for paper_id={paper_id}")
            return batch_results

        # Run batches concurrently
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(_screen_batch, batch_num, batch): batch_num for batch_num, batch in batches}
            for future in as_completed(futures):
                batch_num = futures[future]
                try:
                    batch_results = future.result()
                    all_selected.extend(batch_results)
                except Exception as e:
                    logger.error(f"Screening batch {batch_num} failed: {e}")

        # Clean up temp IDs from original papers
        for p in papers:
            p.pop("_screen_id", None)
        logger.info(f"Screening complete: {len(all_selected)} papers selected from {len(papers)} total")
        return all_selected

    def screen_single(self, paper: dict, requirement: str) -> dict:
        """Screen a single paper."""
        results = self.screen([paper], requirement, threshold="all_selected", batch_size=1)
        if results:
            return results[0]
        return {"relevance": "low", "reason": "Not selected by screening"}
