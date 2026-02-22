"""Multi-strategy PDF downloader.

Download strategies (in order):
1. Direct URL from paper metadata
2. Unpaywall API (for DOI-based papers)
3. DOI redirect following
4. Browser fallback (requires playwright)
"""

from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger(__name__)


class PDFDownloader:
    """Download PDFs with multi-strategy fallback and circuit breaker."""

    def __init__(
        self,
        output_dir: Path | str,
        cookies_file: str | None = None,
        openalex_mailto: str | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cookies_file = cookies_file
        self.openalex_mailto = openalex_mailto or os.environ.get("OPENALEX_MAILTO", "user@example.com")
        self.failed_domains: set[str] = set()

        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/pdf,*/*",
        }

    def download_batch(
        self,
        papers: list[dict],
        max_papers: int | None = None,
        num_threads: int = 4,
        delay_between: float = 0.5,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> dict:
        """Download PDFs for multiple papers using thread pool.

        Args:
            papers: List of paper dicts with pdf_url, doi, url fields.
            max_papers: Maximum number to download.
            num_threads: Thread pool size.
            delay_between: Delay between downloads (seconds).
            on_progress: Callback(current, total) for progress reporting.

        Returns:
            Stats dict with success/fail/skip counts and downloaded list.
        """
        to_download = papers[:max_papers] if max_papers else papers
        total = len(to_download)
        logger.info(f"Downloading {total} PDFs with {num_threads} threads")

        stats = {"success": 0, "failed": 0, "skipped": 0, "downloaded": []}

        def _download_one(paper):
            time.sleep(delay_between)
            return self.download_single(paper)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = {executor.submit(_download_one, p): p for p in to_download}
            for i, future in enumerate(as_completed(futures)):
                paper = futures[future]
                try:
                    result = future.result()
                    if result:
                        stats["success"] += 1
                        stats["downloaded"].append({**paper, "pdf_path": str(result)})
                    else:
                        stats["failed"] += 1
                except Exception as e:
                    logger.error(f"Download error for '{paper.get('title', '?')}': {e}")
                    stats["failed"] += 1

                if on_progress:
                    on_progress(i + 1, total)

        logger.info(
            f"Download complete: {stats['success']} success, {stats['failed']} failed, {stats['skipped']} skipped"
        )
        return stats

    def download_single(self, paper: dict) -> Path | None:
        """Download a single paper's PDF. Returns path or None."""
        title = paper.get("title", "untitled")
        safe_title = re.sub(r"[^\w\s-]", "", title)[:100].strip()
        dest = self.output_dir / f"{safe_title}.pdf"

        # Skip if already downloaded
        if dest.exists() and dest.stat().st_size > 1024:
            logger.debug(f"Already exists: {dest.name}")
            return dest

        # Build candidate URLs
        urls = []
        if paper.get("pdf_url"):
            urls.append(paper["pdf_url"])
        doi = paper.get("doi")
        if doi:
            if not doi.startswith("http"):
                urls.append(f"https://doi.org/{doi}")
            else:
                urls.append(doi)
        if paper.get("url"):
            urls.append(paper["url"])

        # Try each URL
        for url in urls:
            domain = urlparse(url).netloc
            if domain in self.failed_domains:
                continue

            content = self._fetch_content(url)
            if content and self._is_valid_pdf(content):
                return self._save_pdf(dest, content)

            # Try extracting PDF link from HTML
            if content:
                pdf_url = self._extract_pdf_from_html(content, url)
                if pdf_url:
                    pdf_content = self._fetch_content(pdf_url)
                    if pdf_content and self._is_valid_pdf(pdf_content):
                        return self._save_pdf(dest, pdf_content)

        # Try Unpaywall
        if doi:
            unpaywall_url = self._get_unpaywall_url(doi)
            if unpaywall_url:
                content = self._fetch_content(unpaywall_url)
                if content and self._is_valid_pdf(content):
                    return self._save_pdf(dest, content)

        # Try browser fallback
        for url in urls[:1]:  # Only try first URL with browser
            content = self._browser_download(url)
            if content and self._is_valid_pdf(content):
                return self._save_pdf(dest, content)

        logger.warning(f"All strategies failed for: {title}")
        return None

    def _fetch_content(self, url: str, referer: str | None = None) -> bytes | None:
        """Fetch URL content with fallback to curl_cffi."""
        headers = {**self.headers}
        if referer:
            headers["Referer"] = referer

        try:
            resp = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
            if resp.status_code == 200:
                return resp.content
        except Exception as e:
            logger.debug(f"requests failed for {url}: {e}")

        # Try curl_cffi if available
        try:
            from curl_cffi import requests as curl_requests

            resp = curl_requests.get(url, headers=headers, timeout=30, impersonate="chrome")
            if resp.status_code == 200:
                return resp.content
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"curl_cffi failed for {url}: {e}")

        return None

    def _is_valid_pdf(self, content: bytes) -> bool:
        """Check if content is a valid PDF."""
        return content[:5] == b"%PDF-" and len(content) > 1024

    def _extract_pdf_from_html(self, content: bytes, base_url: str) -> str | None:
        """Try to find PDF link in HTML content."""
        try:
            text = content.decode("utf-8", errors="ignore")
            patterns = [
                r'href=["\']([^"\']*\.pdf[^"\']*)["\']',
                r'content=["\']([^"\']*\.pdf[^"\']*)["\']',
                r'(https?://[^\s"\'<>]*\.pdf)',
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    url = match.group(1)
                    if not url.startswith("http"):
                        url = urljoin(base_url, url)
                    return url
        except Exception:
            pass
        return None

    def _get_unpaywall_url(self, doi: str) -> str | None:
        """Get open access PDF URL from Unpaywall."""
        try:
            clean_doi = doi.replace("https://doi.org/", "")
            url = f"https://api.unpaywall.org/v2/{clean_doi}?email={self.openalex_mailto}"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                best = data.get("best_oa_location", {})
                if best:
                    return best.get("url_for_pdf") or best.get("url")
        except Exception as e:
            logger.debug(f"Unpaywall failed for {doi}: {e}")
        return None

    def _browser_download(self, url: str) -> bytes | None:
        """Download using headless browser (requires playwright)."""
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                resp = page.goto(url, wait_until="networkidle", timeout=30000)
                time.sleep(5)
                content = resp.body() if resp else None
                browser.close()
                return content
        except ImportError:
            logger.debug("playwright not installed, skipping browser fallback")
        except Exception as e:
            logger.debug(f"Browser download failed for {url}: {e}")
        return None

    def _save_pdf(self, dest: Path, content: bytes) -> Path:
        """Save PDF content to file."""
        dest.write_bytes(content)
        logger.info(f"Saved: {dest.name} ({len(content)} bytes)")
        return dest
