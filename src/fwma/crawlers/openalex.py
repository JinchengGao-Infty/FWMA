"""OpenAlex paper crawler.

Supports rich filtering: keywords, year range, fields, venues,
publication types, open access, citation count.
"""

from __future__ import annotations

import logging
import time
from threading import Lock

import requests

logger = logging.getLogger(__name__)


class OpenAlexCrawler:
    """Crawl papers from OpenAlex API."""

    BASE_URL = "https://api.openalex.org/works"

    def __init__(self, mailto: str | None = None):
        self.mailto = mailto
        self.search_lock = Lock()

    def _build_filter_params(
        self,
        keywords,
        year_min=None,
        year_max=None,
        fields=None,
        venues=None,
        publication_types=None,
        open_access=None,
        citation_min=None,
    ) -> str | None:
        filters = []
        if year_min or year_max:
            year_min = year_min or 1900
            year_max = year_max or 2100
            filters.append(f"from_publication_date:{year_min}-01-01")
            filters.append(f"to_publication_date:{year_max}-12-31")
        if fields:
            if isinstance(fields, str):
                fields = [fields]
            if fields:
                field_filters = [f"concepts.display_name.search:{f}" for f in fields]
                filters.append("(" + "|".join(field_filters) + ")")
        if venues:
            if isinstance(venues, str):
                venues = [venues]
            venue_filters = [f"host_venue.display_name.search:{v}" for v in venues]
            filters.append("(" + "|".join(venue_filters) + ")")
        if publication_types:
            if isinstance(publication_types, str):
                publication_types = [publication_types]
            type_filters = [f"type:{t}" for t in publication_types]
            filters.append("(" + "|".join(type_filters) + ")")
        if open_access is not None:
            filters.append(f"is_oa:{str(open_access).lower()}")
        if citation_min:
            filters.append(f"cited_by_count:>{citation_min}")
        return ",".join(filters) if filters else None

    def _search_papers(
        self,
        keywords,
        year_min=None,
        year_max=None,
        fields=None,
        venues=None,
        publication_types=None,
        open_access=None,
        citation_min=None,
        per_page=100,
        page=1,
    ) -> tuple[list[dict], dict]:
        params = {"per-page": min(per_page, 200), "page": page}
        if self.mailto:
            params["mailto"] = self.mailto
        if keywords:
            if isinstance(keywords, list):
                keywords = " OR ".join(keywords)
            params["search"] = keywords
        filter_str = self._build_filter_params(
            keywords,
            year_min,
            year_max,
            fields,
            venues,
            publication_types,
            open_access,
            citation_min,
        )
        if filter_str:
            params["filter"] = filter_str

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.get(self.BASE_URL, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                return data.get("results", []), data.get("meta", {})
            except Exception as e:
                logger.warning("OpenAlex request failed (attempt %d): %s", attempt + 1, e)
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                return [], {}
        return [], {}

    def _normalize_paper(self, work: dict) -> dict:
        authors = [a.get("author", {}).get("display_name", "Unknown") for a in work.get("authorships", [])]
        pdf_url = None
        best_oa = work.get("best_oa_location") or {}
        pdf_url = best_oa.get("pdf_url") or best_oa.get("landing_page_url")
        if not pdf_url:
            primary = work.get("primary_location") or {}
            pdf_url = primary.get("pdf_url")
        if not pdf_url and work.get("open_access", {}).get("is_oa"):
            pdf_url = work.get("open_access", {}).get("oa_url")

        host_venue = work.get("host_venue", {})
        venue = host_venue.get("display_name", "Unknown")
        pub_date = work.get("publication_date", "")
        year = pub_date.split("-")[0] if pub_date else None

        return {
            "id": work.get("id", ""),
            "paperId": work.get("id", ""),
            "title": work.get("title", ""),
            "authors": authors,
            "year": int(year) if year and year.isdigit() else None,
            "venue": venue,
            "abstract": work.get("abstract", ""),
            "citationCount": work.get("cited_by_count", 0),
            "publicationDate": work.get("publication_date", ""),
            "pdf_url": pdf_url,
            "doi": work.get("doi", ""),
            "url": work.get("id", ""),
        }

    def fetch_papers(
        self,
        keywords,
        year_min=None,
        year_max=None,
        fields=None,
        venues=None,
        publication_types=None,
        open_access=None,
        citation_min=None,
        limit=100,
        max_pages=5,
    ) -> list[dict]:
        all_papers = []
        per_page = min(100, limit)
        for page in range(1, max_pages + 1):
            if len(all_papers) >= limit:
                break
            results, meta = self._search_papers(
                keywords,
                year_min,
                year_max,
                fields,
                venues,
                publication_types,
                open_access,
                citation_min,
                per_page=per_page,
                page=page,
            )
            if not results:
                break
            for work in results:
                all_papers.append(self._normalize_paper(work))
                if len(all_papers) >= limit:
                    break
            total = meta.get("count", 0)
            logger.info("OpenAlex page %d: got %d papers (total: %d)", page, len(results), total)
            if len(results) < per_page:
                break
            time.sleep(0.5)
        return all_papers[:limit]
