"""arXiv paper crawler."""

from __future__ import annotations

import logging
from datetime import datetime

import arxiv

logger = logging.getLogger(__name__)


class ArxivCrawler:
    """Crawl papers from arXiv API using the arxiv Python package."""

    def fetch_papers(
        self,
        keywords: list[str],
        categories: list[str] | None = None,
        year_min: int | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Search arXiv for papers matching criteria.

        Args:
            keywords: Search terms (joined with OR).
            categories: arXiv category prefixes to filter (e.g., ["cs.AI", "cs.CL"]).
            year_min: Minimum publication year.
            limit: Maximum number of results.

        Returns:
            List of normalized paper dicts.
        """
        all_terms = []
        for kw in keywords:
            all_terms.extend(kw.split())
        query = " AND ".join(all_terms)
        logger.info(f"Searching arXiv: query='{query}', limit={limit}")

        search = arxiv.Search(
            query=query,
            max_results=limit,  # don't over-fetch; filtering happens post-hoc
            sort_by=arxiv.SortCriterion.SubmittedDate,
        )

        papers = []
        for result in search.results():
            # Year filter
            if year_min and result.published.year < year_min:
                continue

            # Category filter
            if categories:
                result_cats = result.categories
                if not any(rc.startswith(cat) for rc in result_cats for cat in categories):
                    continue

            papers.append(self._normalize_paper(result))
            if len(papers) >= limit:
                break

        logger.info(f"arXiv: found {len(papers)} papers")
        return papers

    def _normalize_paper(self, result) -> dict:
        """Normalize arxiv.Result to standard paper dict."""
        doi = None
        for link in result.links:
            if hasattr(link, "title") and link.title == "doi":
                doi = link.href

        return {
            "id": result.entry_id,
            "title": result.title,
            "authors": [a.name for a in result.authors],
            "year": result.published.year,
            "venue": "arXiv",
            "abstract": result.summary,
            "pdf_url": result.pdf_url,
            "doi": doi,
            "url": result.entry_id,
            "source": "arxiv",
            "categories": result.categories,
        }
