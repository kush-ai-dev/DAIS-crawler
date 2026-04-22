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
import requests
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl

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

# In-memory storage
crawl_jobs: dict = {}
webhooks: dict = {}  # Format: {job_id: [webhook_urls]}


# ─────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────

class PageAuditRequest(BaseModel):
    url: str
    force_playwright: bool = False
    webhook_url: Optional[str] = None


class SiteCrawlRequest(BaseModel):
    seed_url: str
    max_pages: int = 50
    respect_robots: bool = True
    crawl_delay_ms: int = 500
    webhook_url: Optional[str] = None


class WebhookRegistration(BaseModel):
    job_id: str
    webhook_url: str
    events: List[str] = ["completed", "failed"]  # Events to trigger on


class WebhookEvent(BaseModel):
    event: str
    job_id: str
    status: str
    timestamp: str
    data: dict


# ─────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────

def trigger_webhook(job_id: str, event: str, job_data: dict):
    """Send webhook notification asynchronously"""
    if job_id not in webhooks:
        return
    
    webhook_urls = webhooks.get(job_id, [])
    for webhook_url in webhook_urls:
        def send_notification():
            try:
                payload = {
                    "event": event,
                    "job_id": job_id,
                    "status": job_data.get("status"),
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": job_data,
                }
                response = requests.post(
                    webhook_url,
                    json=payload,
                    timeout=10,
                )
                response.raise_for_status()
            except Exception as e:
                print(f"Webhook failed for {webhook_url}: {str(e)}")
        
        # Send webhook in background thread
        thread = threading.Thread(target=send_notification, daemon=True)
        thread.start()


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
    Body: {"url": "https://example.com", "webhook_url": "https://your-frontend.com/webhook"}
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

    response_data = {
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
    
    # Trigger webhook if provided
    if req.webhook_url:
        def send_webhook():
            try:
                requests.post(req.webhook_url, json=response_data, timeout=10)
            except Exception as e:
                print(f"Webhook failed: {str(e)}")
        
        thread = threading.Thread(target=send_webhook, daemon=True)
        thread.start()
    
    return response_data


@app.post("/audit/site")
def start_site_crawl(req: SiteCrawlRequest, background_tasks: BackgroundTasks):
    """
    Kick off a full site crawl. Returns job_id immediately.
    Poll GET /audit/site/{job_id} for results.
    Optionally provide webhook_url to get notified on completion.
    
    Postman: POST http://localhost:8000/audit/site
    Body: {
        "seed_url": "https://example.com", 
        "max_pages": 30,
        "webhook_url": "https://your-frontend.com/webhook"
    }
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
    
    # Store webhook URL if provided
    if req.webhook_url:
        webhooks[job_id] = [req.webhook_url]

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
            
            # Trigger webhook on completion
            trigger_webhook(job_id, "completed", {
                "job_id": job_id,
                "status": "completed",
                "seed_url": req.seed_url,
                "summary": result.get("summary"),
                "aggregated_issues": result.get("aggregated_issues"),
            })

        except Exception as e:
            crawl_jobs[job_id]["status"] = "failed"
            crawl_jobs[job_id]["error"] = str(e)
            crawl_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
            
            # Trigger webhook on failure
            trigger_webhook(job_id, "failed", {
                "job_id": job_id,
                "status": "failed",
                "seed_url": req.seed_url,
                "error": str(e),
            })

    # Run in background thread so API responds immediately
    thread = threading.Thread(target=run_crawl, daemon=True)
    thread.start()

    return {
        "status": "queued",
        "job_id": job_id,
        "poll_url": f"/audit/site/{job_id}",
        "webhook_registered": req.webhook_url is not None,
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
    webhooks.clear()
    return {"message": "All jobs cleared."}


# ─────────────────────────────────────────────
# Webhook Management Endpoints
# ─────────────────────────────────────────────

@app.post("/webhook/register")
def register_webhook(registration: WebhookRegistration):
    """
    Register a webhook for a specific job.
    The webhook will be called when the job completes or fails.
    
    Body: {
        "job_id": "uuid-here",
        "webhook_url": "https://your-frontend.com/webhook",
        "events": ["completed", "failed"]
    }
    """
    if registration.job_id not in crawl_jobs:
        raise HTTPException(status_code=404, detail=f"Job {registration.job_id} not found")
    
    if registration.job_id not in webhooks:
        webhooks[registration.job_id] = []
    
    # Avoid duplicate URLs
    if registration.webhook_url not in webhooks[registration.job_id]:
        webhooks[registration.job_id].append(registration.webhook_url)
    
    return {
        "status": "registered",
        "job_id": registration.job_id,
        "webhook_url": registration.webhook_url,
        "events": registration.events,
    }


@app.get("/webhook/list/{job_id}")
def list_webhooks(job_id: str):
    """
    List all registered webhooks for a job.
    
    GET /webhook/list/{job_id}
    """
    if job_id not in crawl_jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    return {
        "job_id": job_id,
        "webhooks": webhooks.get(job_id, []),
        "count": len(webhooks.get(job_id, [])),
    }


@app.delete("/webhook/{job_id}/{webhook_url}")
def unregister_webhook(job_id: str, webhook_url: str):
    """
    Unregister a webhook from a job.
    
    DELETE /webhook/{job_id}/{webhook_url}
    Note: webhook_url should be URL encoded
    """
    if job_id not in crawl_jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    if job_id in webhooks and webhook_url in webhooks[job_id]:
        webhooks[job_id].remove(webhook_url)
        
        # Clean up empty entries
        if not webhooks[job_id]:
            del webhooks[job_id]
    
    return {
        "status": "unregistered",
        "job_id": job_id,
        "webhook_url": webhook_url,
    }


@app.delete("/webhook/{job_id}")
def clear_webhooks(job_id: str):
    """
    Clear all webhooks for a job.
    
    DELETE /webhook/{job_id}
    """
    if job_id not in crawl_jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    count = len(webhooks.get(job_id, []))
    if job_id in webhooks:
        del webhooks[job_id]
    
    return {
        "status": "cleared",
        "job_id": job_id,
        "cleared_count": count,
    }


@app.post("/webhook/test")
def test_webhook(webhook_url: str):
    """
    Test a webhook URL by sending a test payload.
    
    Body: {"webhook_url": "https://your-frontend.com/webhook"}
    """
    test_payload = {
        "event": "test",
        "job_id": "test-webhook",
        "status": "test",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "message": "This is a test webhook from DAIS Crawler",
            "documentation": "https://github.com/yourusername/DAIS-crawler",
        },
    }
    
    try:
        response = requests.post(webhook_url, json=test_payload, timeout=10)
        response.raise_for_status()
        
        return {
            "status": "success",
            "webhook_url": webhook_url,
            "response_code": response.status_code,
            "message": "Test webhook sent successfully",
        }
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=408, detail="Webhook request timed out")
    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=502, detail="Could not connect to webhook URL")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook test failed: {str(e)}")
