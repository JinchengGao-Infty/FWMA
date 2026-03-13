"""Research pipeline orchestrator.

Coordinates the full literature review workflow:
suggest → crawl → screen → download → review → report
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fwma.crawlers.arxiv import ArxivCrawler
from fwma.crawlers.openalex import OpenAlexCrawler
from fwma.crawlers.openreview import OpenReviewCrawler
from fwma.download.downloader import PDFDownloader
from fwma.llm.client import LLMClient
from fwma.parliament.debate import Parliament
from fwma.parliament.review import review_paper
from fwma.prompts.roles.chair import SYSTEM_PROMPT as CHAIR_PROMPT
from fwma.prompts.zh import Step0Prompts
from fwma.report.generator import ReportGenerator
from fwma.screening.screener import Screener

logger = logging.getLogger(__name__)


class ResearchPipeline:
    """End-to-end research pipeline orchestrator."""

    def __init__(
        self,
        run_dir: str | Path,
        screener_model: str = "openai/gpt-4o",
        chair_model: str = "gemini/gemini-2.5-pro",
        member1_model: str = "anthropic/claude-sonnet-4",
        member2_model: str = "openai/gpt-4o",
        openalex_mailto: str | None = None,
        cookies_file: str | None = None,
    ):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # Sub-directories
        self.crawl_dir = self.run_dir / "crawl"
        self.screen_dir = self.run_dir / "screen"
        self.download_dir = self.run_dir / "download"
        self.review_dir = self.run_dir / "review"
        self.report_dir = self.run_dir / "report"
        self.config_path = self.run_dir / "config.json"

        for d in [self.crawl_dir, self.screen_dir, self.download_dir, self.review_dir, self.report_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Components
        self.client = LLMClient()
        self.screener = Screener(model=screener_model)
        self.parliament = Parliament(
            chair_model=chair_model,
            member1_model=member1_model,
            member2_model=member2_model,
        )
        self.report_gen = ReportGenerator(model=chair_model)
        self.openalex_mailto = openalex_mailto or os.environ.get("OPENALEX_MAILTO", "")
        self.cookies_file = cookies_file

    # ------------------------------------------------------------------
    # Step 0: Suggest search strategy
    # ------------------------------------------------------------------
    def suggest(self, requirement: str, model: str = "gemini/gemini-2.5-flash") -> str:
        """AI-powered search strategy suggestion."""
        prompt = Step0Prompts.get_suggestion_prompt(requirement)
        response = self.client.call(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            system_prompt=CHAIR_PROMPT,
        )
        logger.info("Search strategy suggestion generated")
        return response

    # ------------------------------------------------------------------
    # Step 0b: Initialize multi-source config
    # ------------------------------------------------------------------
    def init_config(
        self, requirement: str, sources: list[dict] | None = None, model: str = "gemini/gemini-2.5-flash"
    ) -> dict:
        """Initialize research config. If sources provided, use them directly.
        Otherwise, use AI to generate config."""
        if self.config_path.exists():
            logger.info(f"Config already exists at {self.config_path}, loading")
            with open(self.config_path) as f:
                return json.load(f)

        if sources:
            config = {
                "user_requirement": requirement,
                "sources": sources,
                "created_at": datetime.now().isoformat(),
            }
        else:
            # AI-generated config
            prompt = Step0Prompts.get_multi_source_prompt(requirement)
            response = self.client.call(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                system_prompt=Step0Prompts.MULTI_SOURCE_SYSTEM_PROMPT,
            )
            from fwma.core.utils import parse_json_response

            config_data = parse_json_response(response)
            config = {
                "user_requirement": requirement,
                "sources": config_data.get("sources", []) if isinstance(config_data, dict) else [],
                "research_summary": config_data.get("research_summary", ""),
                "search_strategy": config_data.get("search_strategy", ""),
                "created_at": datetime.now().isoformat(),
            }

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info(f"Config saved to {self.config_path}")
        return config

    # ------------------------------------------------------------------
    # Step 1: Crawl papers from multiple sources
    # ------------------------------------------------------------------
    def crawl(self, sources: list[dict], on_progress: Callable | None = None) -> list[dict]:
        """Crawl papers from multiple sources with dedup."""
        metadata_path = self.crawl_dir / "papers_metadata.json"
        if metadata_path.exists():
            logger.info("Papers metadata already exists, loading")
            with open(metadata_path) as f:
                return json.load(f)

        all_papers = []
        seen_titles = set()

        for idx, source in enumerate(sources):
            source_type = source.get("type", source.get("crawler_type", ""))
            logger.info(f"Crawling source {idx + 1}/{len(sources)}: {source_type}")

            try:
                papers = self._crawl_single(source)
                # Dedup by title
                for paper in papers:
                    title_key = paper.get("title", "").lower().strip()
                    if title_key and title_key not in seen_titles:
                        seen_titles.add(title_key)
                        all_papers.append(paper)

                logger.info(f"Source {idx + 1}: {len(papers)} papers, {len(all_papers)} total after dedup")
            except Exception as e:
                logger.error(f"Crawl source {idx + 1} failed: {e}")

            # Rate limit: pause between arXiv sources to avoid 429
            if source_type == "arxiv" and idx < len(sources) - 1:
                next_type = sources[idx + 1].get("type", sources[idx + 1].get("crawler_type", ""))
                if next_type == "arxiv":
                    delay = 5.0
                    logger.debug(f"Rate limit: waiting {delay}s between arXiv sources")
                    time.sleep(delay)

            if on_progress:
                on_progress(idx + 1, len(sources))

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(all_papers, f, ensure_ascii=False, indent=2)
        logger.info(f"Crawl complete: {len(all_papers)} unique papers saved")
        return all_papers

    def _crawl_single(self, source: dict) -> list[dict]:
        """Crawl a single source."""
        source_type = source.get("type", source.get("crawler_type", ""))
        query = source.get("query", source)

        if source_type == "openalex":
            crawler = OpenAlexCrawler(mailto=self.openalex_mailto)
            return crawler.fetch_papers(
                keywords=query.get("keywords", []),
                year_min=query.get("year_from") or query.get("year_min"),
                year_max=query.get("year_to") or query.get("year_max"),
                fields=query.get("fields"),
                limit=query.get("limit", 200),
                open_access=query.get("open_access", False),
            )
        elif source_type == "arxiv":
            crawler = ArxivCrawler()
            return crawler.fetch_papers(
                keywords=query.get("keywords", []),
                categories=query.get("categories"),
                year_min=query.get("year_from") or query.get("year_min"),
                limit=query.get("limit", 200),
            )
        elif source_type == "openreview":
            crawler = OpenReviewCrawler()
            return crawler.fetch_papers(
                venue=query.get("venue"),
                keywords=query.get("keywords"),
                limit=query.get("limit", 200),
            )
        else:
            raise ValueError(f"Unknown source type: {source_type}")

    # ------------------------------------------------------------------
    # Step 2: Screen papers
    # ------------------------------------------------------------------
    def screen(self, papers: list[dict], requirement: str, threshold: str = "high_medium") -> list[dict]:
        """Screen papers for relevance with incremental saves."""
        screened_path = self.screen_dir / "screened_papers.json"

        existing = []
        if screened_path.exists():
            with open(screened_path) as f:
                existing = json.load(f)
            if len(existing) >= len(papers):
                logger.info("Screening already complete, loading")
                return existing

        # Use incremental screening: save after each batch
        screened_ids = {p.get("paper", {}).get("id") or p.get("id") for p in existing}
        remaining = [p for p in papers if p.get("id") not in screened_ids]
        all_selected = list(existing)
        batch_size = 50

        for i in range(0, len(remaining), batch_size):
            batch = remaining[i : i + batch_size]
            batch_results = self.screener.screen(
                papers=batch,
                requirement=requirement,
                threshold=threshold,
            )
            all_selected.extend(batch_results)

            # Save after each batch (crash-safe)
            with open(screened_path, "w", encoding="utf-8") as f:
                json.dump(all_selected, f, ensure_ascii=False, indent=2)
            logger.info(f"Screening progress: {min(i + batch_size, len(remaining))}/{len(remaining)} papers, {len(all_selected)} selected so far")

        logger.info(f"Screening complete: {len(all_selected)} papers selected")
        return all_selected

    # ------------------------------------------------------------------
    # Step 3: Download PDFs
    # ------------------------------------------------------------------
    def download(self, papers: list[dict], concurrency: int = 8, on_progress: Callable | None = None) -> list[dict]:
        """Download PDFs for screened papers."""
        downloaded_path = self.download_dir / "downloaded_papers.json"

        existing = []
        if downloaded_path.exists():
            with open(downloaded_path) as f:
                existing = json.load(f)

        # Find papers needing download
        existing_ids = {p.get("id") for p in existing if p.get("local_path")}
        to_download = [p for p in papers if p.get("id") not in existing_ids]

        if not to_download:
            logger.info("All papers already downloaded")
            return existing

        logger.info(f"Downloading {len(to_download)} papers (concurrency={concurrency})")

        pdf_dir = self.download_dir / "pdfs"
        downloader = PDFDownloader(
            output_dir=pdf_dir,
            cookies_file=self.cookies_file,
        )
        results = downloader.download_batch(to_download, num_threads=concurrency, on_progress=on_progress)

        # Merge with existing
        all_downloaded = existing + results.get("downloaded", [])

        with open(downloaded_path, "w", encoding="utf-8") as f:
            json.dump(all_downloaded, f, ensure_ascii=False, indent=2)
        logger.info(f"Download complete: {len(all_downloaded)} papers with PDFs")
        return all_downloaded

    # ------------------------------------------------------------------
    # Step 4: Review papers with AI Parliament
    # ------------------------------------------------------------------
    def review(
        self, papers: list[dict], requirement: str, max_rounds: int = 5, on_progress: Callable | None = None
    ) -> list[dict]:
        """Review papers using AI Parliament debate."""
        # Filter papers with PDFs
        papers_with_pdf = [p for p in papers if p.get("local_path")]
        if not papers_with_pdf:
            logger.warning("No papers with PDFs to review")
            return []

        # Resume: check existing reviews
        existing_reviews = []
        reviewed_ids = set()
        for review_file in self.review_dir.glob("*_review.json"):
            try:
                with open(review_file) as f:
                    review = json.load(f)
                    existing_reviews.append(review)
                    paper_id = review.get("paper_info", {}).get("id", "")
                    if paper_id:
                        reviewed_ids.add(str(paper_id))
            except Exception:
                continue

        to_review = [p for p in papers_with_pdf if str(p.get("id")) not in reviewed_ids]
        logger.info(f"Reviewing {len(to_review)} papers ({len(reviewed_ids)} already done)")

        for idx, paper in enumerate(to_review):
            logger.info(f"Reviewing paper {idx + 1}/{len(to_review)}: {paper.get('title', 'Unknown')[:60]}")
            try:
                pdf_path = Path(paper["local_path"])
                result = review_paper(
                    paper=paper,
                    user_requirement=requirement,
                    parliament=self.parliament,
                    pdf_path=pdf_path,
                )

                # Save per-paper review
                paper_id = paper.get("id", f"paper_{idx}")
                review_path = self.review_dir / f"{paper_id}_review.json"
                with open(review_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)

                existing_reviews.append(result)
            except Exception as e:
                logger.error(f"Review failed for {paper.get('title', 'Unknown')}: {e}")

            if on_progress:
                on_progress(idx + 1, len(to_review))

        logger.info(f"Review complete: {len(existing_reviews)} papers reviewed")
        return existing_reviews

    # ------------------------------------------------------------------
    # Step 5: Generate report
    # ------------------------------------------------------------------
    def report(self, reviews: list[dict], requirement: str, format: str = "markdown") -> str:
        """Generate research summary report."""
        content = self.report_gen.generate(
            reviews=reviews,
            requirement=requirement,
            format=format,
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = "md" if format == "markdown" else "json"
        output_path = self.report_dir / f"report_{timestamp}.{ext}"
        self.report_gen.save(content, output_path)

        logger.info(f"Report saved to {output_path}")
        return content

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------
    def run_full(
        self,
        requirement: str,
        sources: list[dict] | None = None,
        threshold: str = "high_medium",
        max_papers: int | None = None,
        concurrency: int = 8,
        max_rounds: int = 5,
        on_progress: Callable | None = None,
    ) -> dict:
        """Run the full research pipeline end-to-end."""
        logger.info("=" * 60)
        logger.info("Starting full research pipeline")
        logger.info("=" * 60)

        # Step 0: Init config
        config = self.init_config(requirement, sources)
        sources = config.get("sources", sources or []) or []

        # Step 1: Crawl
        papers = self.crawl(sources, on_progress=on_progress)

        # Step 2: Screen
        screened = self.screen(papers, requirement, threshold)

        # Step 3: Download
        if max_papers:
            screened = screened[:max_papers]
        downloaded = self.download(screened, concurrency, on_progress=on_progress)

        # Step 4: Review
        reviews = self.review(downloaded, requirement, max_rounds, on_progress=on_progress)

        # Step 5: Report
        report_content = self.report(reviews, requirement)

        logger.info("=" * 60)
        logger.info("Pipeline complete!")
        logger.info(f"  Papers crawled: {len(papers)}")
        logger.info(f"  Papers screened: {len(screened)}")
        logger.info(f"  Papers downloaded: {len(downloaded)}")
        logger.info(f"  Papers reviewed: {len(reviews)}")
        logger.info("=" * 60)

        return {
            "papers": papers,
            "screened": screened,
            "downloaded": downloaded,
            "reviews": reviews,
            "report": report_content,
        }
