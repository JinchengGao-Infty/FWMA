"""OpenReview paper crawler."""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class OpenReviewCrawler:
    """Crawl papers from OpenReview API v2."""

    def __init__(self):
        self.base_url = "https://api2.openreview.net"

    def fetch_papers(
        self,
        venue: str | None = None,
        keywords: list[str] | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Search OpenReview for papers.

        Args:
            venue: Venue ID (e.g., "ICLR.cc/2024/Conference").
            keywords: Search keywords.
            limit: Maximum number of results.

        Returns:
            List of normalized paper dicts.
        """
        papers = []

        if venue:
            logger.info(f"Searching OpenReview venue: {venue}")
            papers = self._fetch_by_venue(venue, limit)
        elif keywords:
            query = " ".join(keywords)
            logger.info(f"Searching OpenReview: query='{query}'")
            papers = self._fetch_by_search(query, limit)

        logger.info(f"OpenReview: found {len(papers)} papers")
        return papers

    def _fetch_by_venue(self, venue: str, limit: int) -> list[dict]:
        """Fetch papers from a specific venue."""
        url = f"{self.base_url}/notes"
        params = {
            "invitation": f"{venue}/-/Submission",
            "limit": limit,
            "details": "original",
        }

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return [self._normalize_paper(note) for note in data.get("notes", [])]
        except Exception as e:
            logger.error(f"OpenReview venue fetch failed: {e}")
            return []

    def _fetch_by_search(self, query: str, limit: int) -> list[dict]:
        """Search papers by keywords."""
        url = f"{self.base_url}/notes/search"
        params = {
            "query": query,
            "limit": limit,
        }

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return [self._normalize_paper(note) for note in data.get("notes", [])]
        except Exception as e:
            logger.error(f"OpenReview search failed: {e}")
            return []

    def _normalize_paper(self, note: dict) -> dict:
        """Normalize OpenReview note to standard paper dict."""
        content = note.get("content", {})

        # Handle both old and new OpenReview formats
        title = content.get("title", {})
        if isinstance(title, dict):
            title = title.get("value", "")

        authors = content.get("authors", {})
        if isinstance(authors, dict):
            authors = authors.get("value", [])

        abstract = content.get("abstract", {})
        if isinstance(abstract, dict):
            abstract = abstract.get("value", "")

        # Extract year from creation date
        cdate = note.get("cdate", 0)
        year = None
        if cdate:
            from datetime import datetime

            year = datetime.fromtimestamp(cdate / 1000).year

        note_id = note.get("id", "")
        invitation = note.get("invitation", "")

        return {
            "id": note_id,
            "title": title,
            "authors": authors if isinstance(authors, list) else [],
            "year": year,
            "venue": invitation.split("/-/")[0] if "/-/" in invitation else invitation,
            "abstract": abstract,
            "pdf_url": f"https://openreview.net/pdf?id={note_id}",
            "doi": None,
            "url": f"https://openreview.net/forum?id={note_id}",
            "source": "openreview",
        }
