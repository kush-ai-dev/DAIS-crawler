"""
DAIS Crawler - FastAPI Server
Hit these endpoints from Postman to test crawl results.

Endpoints:
  POST /audit/page     — Single URL audit
  POST /audit/site     — Full site crawl (async, returns job_id)
  GET  /audit/site/{job_id} — Poll crawl results
  GET  /health         — Health check
"""

import uuid
import json
import threading
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Crawler modules
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler.fetcher import fetch_page
from crawler.extractor import extract_seo_data
from crawler.site_crawler import crawl_site
from dataclasses import asdict

app = FastAPI(
    title="DAIS Crawler API",
    description="DigiDarts AI Search — SEO Crawler MVP",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job store (good enough for MVP testing)
crawl_jobs: dict = {}


# ─────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────

class PageAuditRequest(BaseModel):
    url: str
    force_playwright: bool = False


class SiteCrawlRequest(BaseModel):
    seed_url: str
    max_pages: int = 50
    respect_robots: bool = True
    crawl_delay_ms: int = 500


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "DAIS Crawler API",
        "version": "0.1.0",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/audit/page")
def audit_single_page(req: PageAuditRequest):
    """
    Single URL audit — fetch and run all 50+ checks on one page.
    Returns full SEO report JSON synchronously.
    
    Postman: POST http://localhost:8000/audit/page
    Body: {"url": "https://example.com"}
    """
    url = req.url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    # Fetch
    fetch_result = fetch_page(url, force_playwright=req.force_playwright)

    if not fetch_result["success"]:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Failed to fetch URL",
                "reason": fetch_result.get("error"),
                "url": url,
            }
        )

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
        raise HTTPException(status_code=500, detail={"error": "Extraction failed", "reason": str(e)})

    report_dict = asdict(report)

    return {
        "status": "success",
        "meta": {
            "url": url,
            "final_url": fetch_result["final_url"],
            "rendered_via": fetch_result["rendered_via"],
            "redirect_count": fetch_result["redirect_count"],
            "audited_at": datetime.utcnow().isoformat(),
        },
        "report": report_dict,
        "issues_summary": {
            "total": len(report_dict["issues"]),
            "critical": sum(1 for i in report_dict["issues"] if i["severity"] == "critical"),
            "warning":  sum(1 for i in report_dict["issues"] if i["severity"] == "warning"),
            "info":     sum(1 for i in report_dict["issues"] if i["severity"] == "info"),
        }
    }


@app.post("/audit/site")
def start_site_crawl(req: SiteCrawlRequest, background_tasks: BackgroundTasks):
    """
    Kick off a full site crawl. Returns job_id immediately.
    Poll GET /audit/site/{job_id} for results.
    
    Postman: POST http://localhost:8000/audit/site
    Body: {"seed_url": "https://example.com", "max_pages": 30}
    """
    job_id = str(uuid.uuid4())
    crawl_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "seed_url": req.seed_url,
        "max_pages": req.max_pages,
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
        "progress": {"crawled": 0, "queued": 0},
        "result": None,
        "error": None,
    }

    def run_crawl():
        try:
            crawl_jobs[job_id]["status"] = "running"

            def on_page(page_report, crawled, total):
                crawl_jobs[job_id]["progress"] = {
                    "crawled": crawled,
                    "queued": total,
                    "last_url": page_report.get("url"),
                    "last_score": page_report.get("severity_score"),
                }

            result = crawl_site(
                seed_url=req.seed_url,
                max_pages=req.max_pages,
                respect_robots=req.respect_robots,
                crawl_delay_ms=req.crawl_delay_ms,
                on_page_crawled=on_page,
            )

            crawl_jobs[job_id]["status"] = "completed"
            crawl_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
            crawl_jobs[job_id]["result"] = result

        except Exception as e:
            crawl_jobs[job_id]["status"] = "failed"
            crawl_jobs[job_id]["error"] = str(e)
            crawl_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()

    # Run in background thread so API responds immediately
    thread = threading.Thread(target=run_crawl, daemon=True)
    thread.start()

    return {
        "status": "queued",
        "job_id": job_id,
        "poll_url": f"/audit/site/{job_id}",
        "message": f"Crawl started. Poll /audit/site/{job_id} for progress and results.",
    }


@app.get("/audit/site/{job_id}")
def get_crawl_result(job_id: str, include_pages: bool = True):
    """
    Poll crawl job status and results.
    
    Postman: GET http://localhost:8000/audit/site/{job_id}
    Query param: include_pages=false to get just summary (faster response)
    """
    if job_id not in crawl_jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job = crawl_jobs[job_id]

    if job["status"] in ("queued", "running"):
        return {
            "job_id": job_id,
            "status": job["status"],
            "progress": job["progress"],
            "started_at": job["started_at"],
            "message": "Crawl in progress. Keep polling.",
        }

    if job["status"] == "failed":
        return {
            "job_id": job_id,
            "status": "failed",
            "error": job["error"],
            "started_at": job["started_at"],
            "completed_at": job["completed_at"],
        }

    # Completed
    result = job["result"]
    response = {
        "job_id": job_id,
        "status": "completed",
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
        "summary": result.get("summary"),
        "aggregated_issues": result.get("aggregated_issues"),
    }

    if include_pages:
        response["pages"] = result.get("pages", [])

    return response


@app.get("/audit/site/{job_id}/summary")
def get_crawl_summary(job_id: str):
    """Get just the summary + aggregated issues (no per-page data). Fast for Postman checks."""
    if job_id not in crawl_jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    job = crawl_jobs[job_id]
    if job["status"] != "completed":
        return {"status": job["status"], "progress": job.get("progress")}

    result = job["result"]
    return {
        "status": "completed",
        "domain": result.get("domain"),
        "summary": result.get("summary"),
        "aggregated_issues": result.get("aggregated_issues"),
    }


@app.get("/jobs")
def list_jobs():
    """List all crawl jobs in memory (for debugging)."""
    return [
        {
            "job_id": j["job_id"],
            "seed_url": j["seed_url"],
            "status": j["status"],
            "started_at": j["started_at"],
            "completed_at": j["completed_at"],
            "progress": j.get("progress"),
        }
        for j in crawl_jobs.values()
    ]


@app.delete("/jobs")
def clear_jobs():
    """Clear all in-memory jobs (for testing resets)."""
    crawl_jobs.clear()
    return {"message": "All jobs cleared."}
