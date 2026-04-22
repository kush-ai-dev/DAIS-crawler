# 🏗️ DAIS Crawler - Production Implementation Guide

## Architecture & Scalability

### Current Architecture (MVP)
```
Single Request Flow:
┌──────────────────┐
│ Client Request   │
│ POST /audit/page │
└────────┬─────────┘
         │
         ↓
┌──────────────────────────┐
│ FastAPI Handler          │
│ - URL validation         │
│ - Request parsing        │
└────────┬─────────────────┘
         │
         ↓
┌──────────────────────────┐
│ Multi-Layer Fetcher      │
│ Layer 1: HTTP (curl_cffi)│
│ Layer 2: Playwright      │
│ Layer 3: Playwright+wait │
└────────┬─────────────────┘
         │
         ↓
┌──────────────────────────┐
│ SEO Extractor            │
│ - Parse HTML             │
│ - Run 50+ checks         │
│ - Score calculation      │
└────────┬─────────────────┘
         │
         ↓
┌──────────────────────────┐
│ Response JSON            │
│ - Report metadata        │
│ - Issues list            │
│ - Severity scores        │
└──────────────────────────┘
```

### Site Crawl (Background Jobs)
```
┌────────────────────┐
│ POST /audit/site   │
│ Returns: job_id    │
└────────┬───────────┘
         │
         ├─ Returns immediately (job_id)
         │
         ↓
    ┌─────────────────────────────────────┐
    │ Background Thread (async)           │
    │                                     │
    │ 1. Fetch robots.txt + sitemap       │
    │ 2. Build URL frontier (dedup)       │
    │ 3. Loop: Fetch → Extract → Report  │
    │ 4. Aggregate issues & scores        │
    │ 5. Store result in memory           │
    └─────────────────────────────────────┘
         │
         ↓
┌────────────────────────────────┐
│ Client polls GET /audit/site/{job_id}
│ Receives progress & final results
└────────────────────────────────┘
```

---

## 🔴 Production Issues & Solutions

### Issue 1: In-Memory Job Storage
**Current**: Jobs stored in `crawl_jobs` dict
**Problem**: 
- Lost on restart
- Not shared across multiple instances
- Memory leaks with long-running crawls

**Solution 1: Add Redis (Recommended for MVP Scale)**
```bash
# Step 1: Add Redis to Railway project
railway add redis

# Step 2: Update requirements.txt
redis>=5.0.0
celery>=5.3.0

# Step 3: Update api/server.py
import redis
from celery import Celery

redis_client = redis.from_url(os.getenv("REDIS_URL"))
celery_app = Celery(__name__, broker=os.getenv("REDIS_URL"))

# Store jobs in Redis instead of dict
# Use Celery for async tasks instead of threading
```

**Solution 2: Add PostgreSQL (For Advanced Features)**
```bash
# Step 1: Add PostgreSQL to Railway
railway add postgres

# Step 2: Update requirements.txt
sqlalchemy>=2.0.0
psycopg2-binary>=2.9.0
alembic>=1.12.0

# Step 3: Create models
from sqlalchemy import Column, String, JSON, DateTime
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class CrawlJob(Base):
    __tablename__ = "crawl_jobs"
    job_id = Column(String, primary_key=True)
    status = Column(String)  # queued, running, completed, failed
    result = Column(JSON)
    created_at = Column(DateTime)
    completed_at = Column(DateTime)
```

---

### Issue 2: Ephemeral Storage
**Current**: Files saved to `/output/` directory
**Problem**:
- Files deleted on redeploy
- Not accessible from multiple instances
- Takes up valuable container space

**Solution 1: Use S3 (AWS)**
```bash
# Step 1: Add to requirements.txt
boto3>=1.26.0

# Step 2: Configure in Railway
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_S3_BUCKET=your-bucket

# Step 3: Update save logic
import boto3
s3_client = boto3.client('s3')

def save_report(job_id, report_dict):
    key = f"reports/{job_id}.json"
    s3_client.put_object(
        Bucket=os.getenv("AWS_S3_BUCKET"),
        Key=key,
        Body=json.dumps(report_dict),
        ContentType="application/json"
    )
    return f"s3://{bucket}/{key}"
```

**Solution 2: Store in PostgreSQL (Simpler)**
```python
# Store JSON directly in JSONB column
from sqlalchemy.dialects.postgresql import JSONB

class CrawlReport(Base):
    __tablename__ = "crawl_reports"
    job_id = Column(String, primary_key=True)
    report_data = Column(JSONB)  # Stores full JSON report
    
    def save(self):
        db.session.add(self)
        db.session.commit()
```

---

### Issue 3: Browser Resource Management
**Current**: Each request spawns a Playwright process
**Problem**:
- ~200MB RAM per browser instance
- Slow startup (~3-5 seconds)
- Resource contention on Railway

**Solution: Browser Pool**
```bash
pip install playwright-pool

# Usage:
from playwright_pool import BrowserPool

browser_pool = BrowserPool(
    browser_type="chromium",
    pool_size=2,  # Max concurrent browsers
    headless=True
)

async def fetch_with_pool(url):
    browser = await browser_pool.get_browser()
    try:
        page = await browser.new_page()
        await page.goto(url)
        content = await page.content()
        return content
    finally:
        browser_pool.return_browser(browser)
```

---

### Issue 4: Long-Running Crawls
**Current**: Site crawls run as daemon threads
**Problem**:
- 120-second Railway timeout
- Large sites crash mid-crawl
- No recovery mechanism

**Solution 1: Streaming Results**
```python
@app.post("/audit/site/streaming")
async def crawl_with_streaming(req: SiteCrawlRequest):
    """
    Stream results as they're crawled instead of waiting for completion
    """
    from fastapi.responses import StreamingResponse
    
    async def generate():
        for page in crawl_pages(req.seed_url, req.max_pages):
            report = extract_seo_data(page)
            yield json.dumps(report) + "\n"  # JSONL format
    
    return StreamingResponse(generate(), media_type="application/x-ndjson")
```

**Solution 2: Async Crawling with Timeouts**
```python
import asyncio

@app.post("/audit/site/fast")
async def fast_crawl(req: SiteCrawlRequest):
    """
    Crawl with timeout to respect Railway limits
    """
    try:
        result = await asyncio.wait_for(
            crawl_site_async(req.seed_url, req.max_pages),
            timeout=110.0  # 110 seconds (leave 10s buffer)
        )
        return {"status": "completed", "result": result}
    except asyncio.TimeoutError:
        return {
            "status": "partial",
            "message": "Crawl timed out after 110s. Some pages may be incomplete."
        }
```

---

### Issue 5: No Rate Limiting
**Current**: Anyone can hammer the API
**Problem**:
- Resource exhaustion
- Browser process explosion
- Expensive bandwidth usage

**Solution: Add slowapi**
```bash
pip install slowapi

# Usage:
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/audit/page")
@limiter.limit("10/minute")
async def audit_page(req: PageAuditRequest):
    # Max 10 requests per minute per IP
    ...

@app.post("/audit/site")
@limiter.limit("2/hour")
async def start_crawl(req: SiteCrawlRequest):
    # Max 2 full crawls per hour per IP
    ...
```

---

## 🚀 Recommended Roadmap

### Phase 1: MVP (Current - Ready to Deploy)
- ✅ FastAPI server with basic endpoints
- ✅ In-memory job storage (works for single instance)
- ✅ Playwright browser automation
- ✅ CLI for local testing
- ⏳ Deploy to Railway as-is

### Phase 2: Production-Ready (1-2 weeks)
- ⬜ Add Redis for persistent job queue
- ⬜ Implement database for reports
- ⬜ Add rate limiting
- ⬜ Configure S3 or database storage for outputs
- ⬜ Add comprehensive error handling
- ⬜ Set up monitoring & alerting

### Phase 3: Scale (2-4 weeks)
- ⬜ Async/await throughout (remove threads)
- ⬜ Browser pool for concurrency
- ⬜ Distributed crawling (split domains across workers)
- ⬜ Webhook notifications for job completion
- ⬜ Batch API for multiple URLs

### Phase 4: Enterprise (1-2 months)
- ⬜ User authentication & API keys
- ⬜ Usage billing/quotas
- ⬜ Custom report templates
- ⬜ Scheduled crawls (cron jobs)
- ⬜ Historical trend analysis
- ⬜ White-label dashboard

---

## 🔍 Performance Optimization

### Page Fetch Bottlenecks
```
HTTP Fetch (200-500ms)
↓
Playwright Fetch (3-8s) - only if JS detected
↓
Extraction (500ms-1s)
↓
Total: 0.7s - 9s per page
```

**Optimization 1: Parallel Extraction**
```python
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=3)

async def fetch_and_extract(urls):
    # Fetch sequentially (browser limitation)
    pages = [fetch_page(url) for url in urls]
    
    # Extract in parallel
    reports = list(executor.map(extract_seo_data, pages))
    return reports
```

**Optimization 2: Cache SPA Detection**
```python
# Cache which domains are SPAs to avoid retesting
spa_cache = {}

def fetch_page(url, force_playwright=False):
    domain = urlparse(url).netloc
    
    if domain in spa_cache:
        force_playwright = spa_cache[domain]
    
    # ... fetch logic ...
    
    spa_cache[domain] = needs_playwright
```

**Optimization 3: Compression**
```python
# In railway.json or Procfile, add gzip compression
# This is handled automatically by Railway/nginx
```

---

## 📊 Monitoring Setup

### Key Metrics to Track
```python
from prometheus_client import Counter, Histogram, Gauge
import time

# Request metrics
request_count = Counter(
    'crawler_requests_total',
    'Total requests',
    ['endpoint', 'status']
)

request_duration = Histogram(
    'crawler_request_duration_seconds',
    'Request duration',
    ['endpoint']
)

active_jobs = Gauge(
    'crawler_active_jobs',
    'Number of active crawl jobs'
)

# Usage example:
@app.post("/audit/page")
async def audit_page(req: PageAuditRequest):
    start = time.time()
    try:
        result = fetch_and_extract(req.url)
        request_count.labels(endpoint="/audit/page", status="success").inc()
        return result
    except Exception as e:
        request_count.labels(endpoint="/audit/page", status="error").inc()
        raise
    finally:
        request_duration.labels(endpoint="/audit/page").observe(
            time.time() - start
        )
```

### Set Up Alerts in Railway
```bash
# Monitor for errors
railway logs | grep ERROR

# Monitor memory usage
railway logs | grep "Memory"

# Check for crashes
railway logs | grep "exit code"
```

---

## 🔐 Security Hardening

### 1. Input Validation
```python
from urllib.parse import urlparse
import validators

@app.post("/audit/page")
async def audit_page(req: PageAuditRequest):
    # Validate URL format
    if not validators.url(req.url):
        raise HTTPException(status_code=400, detail="Invalid URL")
    
    # Prevent SSRF attacks
    parsed = urlparse(req.url)
    if parsed.hostname in ("localhost", "127.0.0.1", "0.0.0.0"):
        raise HTTPException(status_code=403, detail="Internal IPs not allowed")
    
    return audit_internal(req.url)
```

### 2. Request Timeouts
```python
# In Playwright fetch
page.goto(url, timeout=30000)  # 30 second timeout

# In requests library
response = requests.get(url, timeout=10)
```

### 3. CORS & Headers
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Restrict
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
    max_age=3600,
)

# Security headers
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response
```

---

## 📚 Code Quality

### Add Testing
```bash
pip install pytest pytest-asyncio pytest-cov

# Test example:
import pytest
from fastapi.testclient import TestClient

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_page_audit():
    response = client.post("/audit/page", json={"url": "https://example.com"})
    assert response.status_code == 200
    assert "report" in response.json()
```

### Code Linting
```bash
pip install pylint black flake8

# Format code
black api/ crawler/

# Lint
flake8 api/ crawler/ --max-line-length=100
```

---

## 🎯 Success Criteria

Your deployment is production-ready when:

- ✅ Dockerfile builds successfully
- ✅ App deploys to Railway without errors
- ✅ `/health` endpoint responds in < 1s
- ✅ `/audit/page` works with real URLs
- ✅ Jobs survive 5+ minute crawls (for Phase 2+)
- ✅ Memory usage stays < 500MB
- ✅ Error logs are clear and actionable
- ✅ Response times are < 15s for most pages

---

**Current Status**: Phase 1 - MVP Ready ✅
**Next**: Deploy to Railway and monitor
