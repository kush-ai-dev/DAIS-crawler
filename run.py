"""
DAIS Crawler - CLI Runner
Run directly from terminal without starting the API server.

Usage:
  python run.py --url https://example.com              # Single page audit
  python run.py --site https://example.com             # Full site crawl
  python run.py --site https://example.com --max 20   # Limit to 20 pages
  python run.py --site https://example.com --no-robots # Ignore robots.txt
"""

import argparse
import json
import os
import sys
from datetime import datetime
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler.fetcher import fetch_page
from crawler.extractor import extract_seo_data
from crawler.site_crawler import crawl_site


def run_single_page(url: str, force_playwright: bool = False):
    print(f"\n── Single Page Audit ──────────────────────────────")
    print(f"  URL: {url}")
    print(f"  Mode: {'Playwright (forced)' if force_playwright else 'HTTP (auto-fallback)'}\n")

    fetch_result = fetch_page(url, force_playwright=force_playwright)

    if not fetch_result["success"]:
        print(f"✗ Fetch failed: {fetch_result['error']}")
        sys.exit(1)

    report = extract_seo_data(
        url=fetch_result["final_url"],
        html=fetch_result["html"],
        status_code=fetch_result["status_code"],
        response_headers=fetch_result["response_headers"],
        load_time_ms=fetch_result["load_time_ms"],
        page_size_kb=fetch_result["page_size_kb"],
        rendered_via=fetch_result["rendered_via"],
    )

    report_dict = asdict(report)

    # Print summary to terminal
    print(f"\n── RESULTS ────────────────────────────────────────")
    print(f"  Rendered via  : {fetch_result['rendered_via'].upper()}")
    print(f"  Status code   : {fetch_result['status_code']}")
    print(f"  Load time     : {fetch_result['load_time_ms']}ms")
    print(f"  Page size     : {fetch_result['page_size_kb']}KB")
    print(f"  Health score  : {report.severity_score}/100")
    print(f"  Title         : {report.title}")
    print(f"  Word count    : {report.word_count}")
    print(f"  Internal links: {report.internal_links}")
    print(f"  Images        : {report.total_images} total, {report.images_missing_alt} missing alt")
    print(f"  Schema types  : {report.schema_types or 'None'}")

    print(f"\n── ISSUES ({len(report_dict['issues'])}) ──────────────────────────────────")
    for issue in sorted(report_dict["issues"], key=lambda i: {"critical":0,"warning":1,"info":2}.get(i["severity"],3)):
        icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(issue["severity"], "•")
        print(f"  {icon} [{issue['severity'].upper()}] {issue['message']}")
        if issue.get("recommendation"):
            print(f"       → {issue['recommendation']}")

    # Save JSON output
    output = {
        "meta": {
            "url": url,
            "final_url": fetch_result["final_url"],
            "rendered_via": fetch_result["rendered_via"],
            "audited_at": datetime.utcnow().isoformat(),
        },
        "report": report_dict,
    }

    os.makedirs("output", exist_ok=True)
    filename = f"output/page_audit_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n✓ Full JSON saved to: {filename}\n")


def run_site_crawl(seed_url: str, max_pages: int, respect_robots: bool, delay_ms: int):
    result = crawl_site(
        seed_url=seed_url,
        max_pages=max_pages,
        respect_robots=respect_robots,
        crawl_delay_ms=delay_ms,
    )

    summary = result["summary"]
    issues  = result["aggregated_issues"]

    print(f"\n── SITE SUMMARY ───────────────────────────────────")
    print(f"  Domain        : {result['domain']}")
    print(f"  Pages crawled : {summary['total_pages_crawled']}")
    print(f"  Health score  : {summary['site_health_score']}/100")
    print(f"  Critical      : {summary['critical_issues']}")
    print(f"  Warnings      : {summary['warning_issues']}")
    print(f"  Info          : {summary['info_issues']}")
    print(f"  Time taken    : {summary['total_crawl_time_seconds']}s")

    print(f"\n── TOP ISSUES ─────────────────────────────────────")
    for issue in issues[:15]:
        icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(issue["severity"], "•")
        print(f"  {icon} [{issue['severity'].upper()}] {issue['issue_type']} — {issue['affected_count']} pages")
        print(f"       → {issue['recommendation']}")

    os.makedirs("output", exist_ok=True)
    filename = f"output/site_crawl_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n✓ Full crawl JSON saved to: {filename}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DAIS Crawler CLI")
    parser.add_argument("--url",        help="Single URL to audit")
    parser.add_argument("--site",       help="Seed URL for full site crawl")
    parser.add_argument("--max",        type=int, default=50, help="Max pages to crawl (default: 50)")
    parser.add_argument("--playwright", action="store_true", help="Force Playwright rendering")
    parser.add_argument("--no-robots",  action="store_true", help="Ignore robots.txt")
    parser.add_argument("--delay",      type=int, default=500, help="Crawl delay in ms (default: 500)")

    args = parser.parse_args()

    if args.url:
        run_single_page(args.url, force_playwright=args.playwright)
    elif args.site:
        run_site_crawl(
            seed_url=args.site,
            max_pages=args.max,
            respect_robots=not args.no_robots,
            delay_ms=args.delay,
        )
    else:
        print("Usage: python run.py --url <URL>  OR  python run.py --site <URL>")
        print("       python run.py --help for all options")
        sys.exit(1)
