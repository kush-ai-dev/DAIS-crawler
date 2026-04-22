"""
DAIS Crawler - Site-Wide Crawl Engine
Manages URL frontier, deduplication, robots.txt, sitemap discovery,
and drives the per-page fetch + extract loop.
"""

import time
import re
import json
import hashlib
from collections import deque
from urllib.parse import urlparse, urljoin, urlunparse
from urllib.robotparser import RobotFileParser
from dataclasses import asdict
from typing import Optional
import requests

from crawler.fetcher import fetch_page
from crawler.extractor import extract_seo_data


CRAWL_DELAY_MS = 500       # polite delay between requests (ms)
DEFAULT_MAX_PAGES = 100
SITEMAP_FETCH_TIMEOUT = 10


# ─────────────────────────────────────────────
# URL Normalization & Deduplication
# ─────────────────────────────────────────────

# Query params to strip (tracking noise)
STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "ref", "source", "mc_cid", "mc_eid",
    "_ga", "hsa_acc", "hsa_cam", "hsa_grp", "hsa_ad",
}


def normalize_url(url: str, base_domain: str) -> Optional[str]:
    """
    Normalize a URL for deduplication:
    - lowercase scheme + host
    - strip tracking params
    - strip fragments
    - strip trailing slash (treat /about/ and /about as same)
    Returns None if the URL should be skipped entirely.
    """
    try:
        parsed = urlparse(url)

        # Only crawl http/https
        if parsed.scheme not in ("http", "https"):
            return None

        # Only crawl same domain
        if parsed.netloc.lower().replace("www.", "") != base_domain.replace("www.", ""):
            return None

        # Strip tracking query params
        if parsed.query:
            from urllib.parse import parse_qs, urlencode
            params = parse_qs(parsed.query, keep_blank_values=True)
            cleaned = {k: v for k, v in params.items() if k not in STRIP_PARAMS}
            query = urlencode(cleaned, doseq=True)
        else:
            query = ""

        # Rebuild normalized URL
        normalized = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",   # strip trailing slash
            "",                                 # params
            query,
            "",                                 # strip fragment
        ))
        return normalized

    except Exception:
        return None


def is_crawlable_url(url: str) -> bool:
    """Skip non-HTML resources by extension."""
    skip_extensions = {
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
        ".mp4", ".mp3", ".avi", ".mov", ".zip", ".tar", ".gz",
        ".css", ".js", ".woff", ".woff2", ".ttf", ".ico",
        ".xml", ".json", ".xlsx", ".docx", ".pptx",
    }
    parsed = urlparse(url)
    path = parsed.path.lower()
    return not any(path.endswith(ext) for ext in skip_extensions)


# ─────────────────────────────────────────────
# robots.txt Parser
# ─────────────────────────────────────────────

def fetch_robots_txt(seed_url: str) -> RobotFileParser:
    parsed = urlparse(seed_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
        print(f"  [robots] Fetched: {robots_url}")
    except Exception as e:
        print(f"  [robots] Could not fetch {robots_url}: {e}")
    return rp


def is_allowed_by_robots(rp: RobotFileParser, url: str, respect_robots: bool) -> bool:
    if not respect_robots:
        return True
    try:
        return rp.can_fetch("*", url)
    except Exception:
        return True


# ─────────────────────────────────────────────
# Sitemap Parser
# ─────────────────────────────────────────────

def fetch_sitemap_urls(seed_url: str) -> list[str]:
    """Try to find and parse sitemap.xml. Returns list of URLs found."""
    parsed = urlparse(seed_url)
    candidates = [
        f"{parsed.scheme}://{parsed.netloc}/sitemap.xml",
        f"{parsed.scheme}://{parsed.netloc}/sitemap_index.xml",
        f"{parsed.scheme}://{parsed.netloc}/sitemap/",
    ]

    discovered = []

    for sitemap_url in candidates:
        try:
            resp = requests.get(sitemap_url, timeout=SITEMAP_FETCH_TIMEOUT, headers={
                "User-Agent": "DAISBot/1.0"
            })
            if resp.status_code == 200 and "xml" in resp.headers.get("content-type", ""):
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.content, "lxml-xml")

                # Handle sitemap index (points to other sitemaps)
                sitemap_tags = soup.find_all("sitemap")
                if sitemap_tags:
                    for s in sitemap_tags:
                        loc = s.find("loc")
                        if loc:
                            sub_urls = _parse_single_sitemap(loc.text.strip())
                            discovered.extend(sub_urls)
                else:
                    urls = _parse_single_sitemap(sitemap_url, resp.content)
                    discovered.extend(urls)

                print(f"  [sitemap] Found {len(discovered)} URLs from {sitemap_url}")
                break  # stop after first successful sitemap
        except Exception as e:
            print(f"  [sitemap] Failed {sitemap_url}: {e}")

    return list(set(discovered))


def _parse_single_sitemap(url: str, content: bytes = None) -> list[str]:
    from bs4 import BeautifulSoup
    try:
        if content is None:
            resp = requests.get(url, timeout=SITEMAP_FETCH_TIMEOUT)
            content = resp.content
        soup = BeautifulSoup(content, "lxml-xml")
        locs = soup.find_all("loc")
        return [loc.text.strip() for loc in locs]
    except Exception:
        return []


# ─────────────────────────────────────────────
# Duplicate Detection (cross-page)
# ─────────────────────────────────────────────

def fingerprint(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return hashlib.md5(text.strip().lower().encode()).hexdigest()


# ─────────────────────────────────────────────
# Main Crawler
# ─────────────────────────────────────────────

def crawl_site(
    seed_url: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    respect_robots: bool = True,
    crawl_delay_ms: int = CRAWL_DELAY_MS,
    on_page_crawled=None,   # optional callback(page_report, index, total_queued)
) -> dict:
    """
    Full site crawl starting from seed_url.
    Returns a complete crawl result dict with per-page reports + aggregated issues.
    """
    start_time = time.time()

    if not seed_url.startswith("http"):
        seed_url = "https://" + seed_url

    parsed_seed = urlparse(seed_url)
    base_domain = parsed_seed.netloc

    print(f"\n{'='*60}")
    print(f"  DAIS CRAWLER — Starting crawl")
    print(f"  Domain  : {base_domain}")
    print(f"  Seed URL: {seed_url}")
    print(f"  Max pages: {max_pages}")
    print(f"  Respect robots.txt: {respect_robots}")
    print(f"{'='*60}\n")

    # ── Step 1: robots.txt ───────────────────────────────────────────
    robots_parser = fetch_robots_txt(seed_url)
    crawl_delay_from_robots = robots_parser.crawl_delay("*") or 0
    effective_delay = max(crawl_delay_ms / 1000, crawl_delay_from_robots)
    print(f"  [config] Crawl delay: {effective_delay:.2f}s\n")

    # ── Step 2: Sitemap discovery ────────────────────────────────────
    sitemap_urls = fetch_sitemap_urls(seed_url)
    print(f"  [sitemap] Total URLs from sitemap: {len(sitemap_urls)}\n")

    # ── Step 3: Initialize URL frontier ─────────────────────────────
    visited     = set()    # normalized URLs already crawled
    queued      = set()    # normalized URLs already in frontier
    frontier    = deque()  # BFS queue

    def enqueue(url: str, source: str = "discovery"):
        norm = normalize_url(url, base_domain)
        if not norm:
            return
        if norm in visited or norm in queued:
            return
        if not is_crawlable_url(norm):
            return
        if not is_allowed_by_robots(robots_parser, norm, respect_robots):
            print(f"  [robots] Blocked: {norm}")
            return
        frontier.append({"url": norm, "source": source})
        queued.add(norm)

    # Seed: sitemap URLs first, then seed URL
    for u in sitemap_urls:
        enqueue(u, source="sitemap")
    enqueue(seed_url, source="seed")

    # ── Step 4: Crawl loop ───────────────────────────────────────────
    page_reports = []
    title_fingerprints    = {}  # fingerprint → url (for dup detection)
    meta_fingerprints     = {}

    crawled_count = 0

    while frontier and crawled_count < max_pages:
        item = frontier.popleft()
        url  = item["url"]

        if url in visited:
            continue
        visited.add(url)
        crawled_count += 1

        print(f"  [{crawled_count:>4}/{max_pages}] Fetching: {url}")

        # Fetch
        fetch_result = fetch_page(url)

        if not fetch_result["success"]:
            print(f"           ✗ Fetch failed: {fetch_result['error']}")
            page_reports.append({
                "url": url,
                "error": fetch_result["error"],
                "status_code": fetch_result["status_code"],
                "rendered_via": fetch_result["rendered_via"],
            })
            continue

        # Extract
        try:
            report = extract_seo_data(
                url=fetch_result["final_url"],
                html=fetch_result["html"],
                status_code=fetch_result["status_code"],
                response_headers=fetch_result["response_headers"],
                load_time_ms=fetch_result["load_time_ms"],
                page_size_kb=fetch_result["page_size_kb"],
                rendered_via=fetch_result["rendered_via"],
            )
        except Exception as e:
            print(f"           ✗ Extraction error: {e}")
            continue

        # Duplicate title / meta detection
        t_fp = fingerprint(report.title)
        m_fp = fingerprint(report.meta_description)

        if t_fp and t_fp in title_fingerprints:
            report.duplicate_title = True
            report.issues.append({
                "check": "duplicate_title",
                "severity": "warning",
                "message": f"Duplicate title detected — same as {title_fingerprints[t_fp]}",
                "value": report.title,
                "recommendation": "Each page should have a unique title tag.",
            })
            report.severity_score = max(0, report.severity_score - 8)
        elif t_fp:
            title_fingerprints[t_fp] = url

        if m_fp and m_fp in meta_fingerprints:
            report.duplicate_meta = True
            report.issues.append({
                "check": "duplicate_meta_description",
                "severity": "warning",
                "message": f"Duplicate meta description — same as {meta_fingerprints[m_fp]}",
                "value": report.meta_description,
                "recommendation": "Write a unique meta description for each page.",
            })
            report.severity_score = max(0, report.severity_score - 5)
        elif m_fp:
            meta_fingerprints[m_fp] = url

        # Discover new internal links from this page
        for link_url in report.internal_link_urls:
            enqueue(link_url, source="link_discovery")

        print(f"           ✓ {fetch_result['rendered_via'].upper()} | "
              f"{fetch_result['status_code']} | "
              f"{fetch_result['load_time_ms']}ms | "
              f"{len(report.issues)} issues | "
              f"score: {report.severity_score}/100")

        page_reports.append(asdict(report))

        # Callback for streaming (e.g. FastAPI SSE)
        if on_page_crawled:
            on_page_crawled(asdict(report), crawled_count, len(frontier) + crawled_count)

        # Polite delay
        if effective_delay > 0:
            time.sleep(effective_delay)

    # ── Step 5: Aggregate issues ─────────────────────────────────────
    total_time = round(time.time() - start_time, 2)
    aggregated_issues = _aggregate_issues(page_reports)
    summary = _build_summary(page_reports, aggregated_issues, crawled_count, total_time)

    print(f"\n{'='*60}")
    print(f"  Crawl complete: {crawled_count} pages in {total_time}s")
    print(f"  Site health score: {summary['site_health_score']}/100")
    print(f"  Total issues: {summary['total_issues']}")
    print(f"{'='*60}\n")

    return {
        "domain": base_domain,
        "seed_url": seed_url,
        "summary": summary,
        "aggregated_issues": aggregated_issues,
        "pages": page_reports,
    }


# ─────────────────────────────────────────────
# Aggregation & Summary
# ─────────────────────────────────────────────

def _aggregate_issues(page_reports: list) -> list:
    """Roll up per-page issues into site-wide issue types."""
    issue_map = {}  # check_type → {severity, messages, affected_urls}

    for page in page_reports:
        if "issues" not in page or not page["issues"]:
            continue
        url = page.get("url", "")
        for issue in page["issues"]:
            check = issue.get("check", "unknown")
            if check not in issue_map:
                issue_map[check] = {
                    "issue_type": check,
                    "severity": issue.get("severity", "info"),
                    "message": issue.get("message", ""),
                    "recommendation": issue.get("recommendation", ""),
                    "affected_urls": [],
                    "affected_count": 0,
                }
            issue_map[check]["affected_urls"].append(url)
            issue_map[check]["affected_count"] += 1

    # Sort: critical first, then by affected count
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    aggregated = sorted(
        issue_map.values(),
        key=lambda x: (severity_order.get(x["severity"], 3), -x["affected_count"])
    )
    return aggregated


def _build_summary(page_reports: list, aggregated_issues: list, crawled: int, total_time: float) -> dict:
    valid_pages = [p for p in page_reports if "severity_score" in p]
    if not valid_pages:
        return {"site_health_score": 0, "total_pages": crawled, "total_issues": 0}

    avg_score = round(sum(p["severity_score"] for p in valid_pages) / len(valid_pages))
    critical = sum(1 for i in aggregated_issues if i["severity"] == "critical")
    warnings = sum(1 for i in aggregated_issues if i["severity"] == "warning")
    infos    = sum(1 for i in aggregated_issues if i["severity"] == "info")

    return {
        "site_health_score": avg_score,
        "total_pages_crawled": crawled,
        "total_pages_with_data": len(valid_pages),
        "total_issues": len(aggregated_issues),
        "critical_issues": critical,
        "warning_issues": warnings,
        "info_issues": infos,
        "avg_page_score": avg_score,
        "total_crawl_time_seconds": total_time,
        "pages_with_errors": crawled - len(valid_pages),
    }
