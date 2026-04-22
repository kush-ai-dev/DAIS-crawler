# 🚀 DAIS Crawler API - Complete Endpoint Reference

**Base URL**: `https://your-railway-app.up.railway.app`  
**API Version**: 0.1.0  
**Documentation**: `GET /docs` for interactive Swagger UI

---

## 📋 Quick Start for Frontend Integration

### 1. Health Check
```bash
GET /health
```
**Response**: `200 OK`
```json
{
  "status": "ok",
  "service": "DAIS Crawler API",
  "version": "0.1.0",
  "timestamp": "2026-04-22T10:30:45.123456"
}
```

### 2. Audit Single Page (Synchronous)
```bash
POST /audit/page
Content-Type: application/json

{
  "url": "https://example.com",
  "force_playwright": false,
  "webhook_url": "https://your-frontend.com/webhook"
}
```

**Response**: `200 OK`
```json
{
  "status": "success",
  "meta": {
    "url": "https://example.com",
    "final_url": "https://example.com",
    "rendered_via": "http",
    "redirect_count": 0,
    "audited_at": "2026-04-22T10:30:45.123456"
  },
  "report": {
    "title": "Example Domain",
    "word_count": 1234,
    "internal_links": 45,
    "total_images": 12,
    "images_missing_alt": 3,
    "schema_types": ["Organization"],
    "severity_score": 78,
    "issues": [
      {
        "severity": "warning",
        "message": "3 images missing alt text",
        "recommendation": "Add descriptive alt text to all images"
      }
    ]
  },
  "issues_summary": {
    "total": 8,
    "critical": 1,
    "warning": 4,
    "info": 3
  }
}
```

---

## 🔄 Site Crawl Flow (Async + Webhook)

### Step 1: Start Site Crawl
```bash
POST /audit/site
Content-Type: application/json

{
  "seed_url": "https://example.com",
  "max_pages": 50,
  "respect_robots": true,
  "crawl_delay_ms": 500,
  "webhook_url": "https://your-frontend.com/api/webhook"
}
```

**Response**: `200 OK`
```json
{
  "status": "queued",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "poll_url": "/audit/site/550e8400-e29b-41d4-a716-446655440000",
  "webhook_registered": true,
  "message": "Crawl started. Poll /audit/site/{job_id} for progress and results."
}
```

### Step 2: Poll for Progress (Optional)
```bash
GET /audit/site/{job_id}?include_pages=false
```

**Response during crawl**: `200 OK`
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "progress": {
    "crawled": 15,
    "queued": 45,
    "last_url": "https://example.com/about",
    "last_score": 82
  },
  "started_at": "2026-04-22T10:30:45.123456",
  "message": "Crawl in progress. Keep polling."
}
```

### Step 3: Webhook Notification (Automatic)
When crawl completes, your webhook endpoint receives:

```json
{
  "event": "completed",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "timestamp": "2026-04-22T10:35:45.123456",
  "data": {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "completed",
    "seed_url": "https://example.com",
    "summary": {
      "total_pages_crawled": 45,
      "site_health_score": 75,
      "critical_issues": 2,
      "warning_issues": 15,
      "info_issues": 32,
      "total_crawl_time_seconds": 120
    },
    "aggregated_issues": [
      {
        "issue_type": "Missing meta descriptions",
        "severity": "warning",
        "affected_count": 12,
        "recommendation": "Add unique meta descriptions (50-160 chars) to all pages"
      }
    ]
  }
}
```

### Step 4: Get Full Results
```bash
GET /audit/site/{job_id}?include_pages=true
```

**Response**: `200 OK`
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "started_at": "2026-04-22T10:30:45.123456",
  "completed_at": "2026-04-22T10:35:45.123456",
  "summary": {
    "total_pages_crawled": 45,
    "site_health_score": 75,
    "critical_issues": 2,
    "warning_issues": 15,
    "info_issues": 32,
    "total_crawl_time_seconds": 120
  },
  "aggregated_issues": [...],
  "pages": [
    {
      "url": "https://example.com",
      "status_code": 200,
      "title": "Example Domain",
      "word_count": 1234,
      "severity_score": 78,
      "issues": [...]
    }
  ]
}
```

---

## 📡 All Endpoints Reference

### Core Crawling Endpoints

#### 1. GET /health
Health check for the API.

**Request**:
```bash
GET /health
```

**Response**: `200 OK`
```json
{
  "status": "ok",
  "service": "DAIS Crawler API",
  "version": "0.1.0",
  "timestamp": "2026-04-22T10:30:45.123456"
}
```

---

#### 2. POST /audit/page
Audit a single URL synchronously (completes in 3-15 seconds).

**Request**:
```bash
POST /audit/page
Content-Type: application/json

{
  "url": "https://example.com/page",
  "force_playwright": false,
  "webhook_url": "https://your-frontend.com/webhook"
}
```

**Parameters**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | Yes | URL to audit (http/https optional) |
| `force_playwright` | boolean | No | Force browser rendering (default: false) |
| `webhook_url` | string | No | Webhook to call with results |

**Response**: `200 OK`
```json
{
  "status": "success",
  "meta": {
    "url": "https://example.com/page",
    "final_url": "https://example.com/page",
    "rendered_via": "http",
    "redirect_count": 0,
    "audited_at": "2026-04-22T10:30:45.123456"
  },
  "report": {
    "title": "Page Title",
    "word_count": 1234,
    "internal_links": 45,
    "external_links": 12,
    "total_images": 8,
    "images_missing_alt": 2,
    "images_missing_title": 1,
    "headings_structure": {...},
    "og_tags": {...},
    "twitter_tags": {...},
    "schema_types": ["Article"],
    "severity_score": 82,
    "issues": [...]
  },
  "issues_summary": {
    "total": 6,
    "critical": 0,
    "warning": 2,
    "info": 4
  }
}
```

**Error Responses**:
- `502 Bad Gateway` - Failed to fetch URL
- `500 Internal Server Error` - Extraction failed

---

#### 3. POST /audit/site
Start an async site-wide crawl (returns immediately with job_id).

**Request**:
```bash
POST /audit/site
Content-Type: application/json

{
  "seed_url": "https://example.com",
  "max_pages": 50,
  "respect_robots": true,
  "crawl_delay_ms": 500,
  "webhook_url": "https://your-frontend.com/api/webhook"
}
```

**Parameters**:
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `seed_url` | string | Required | Starting URL for crawl |
| `max_pages` | integer | 50 | Max pages to crawl |
| `respect_robots` | boolean | true | Honor robots.txt |
| `crawl_delay_ms` | integer | 500 | Delay between requests (ms) |
| `webhook_url` | string | Optional | Webhook for completion notification |

**Response**: `200 OK`
```json
{
  "status": "queued",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "poll_url": "/audit/site/550e8400-e29b-41d4-a716-446655440000",
  "webhook_registered": true,
  "message": "Crawl started. Poll /audit/site/{job_id} for progress and results."
}
```

---

#### 4. GET /audit/site/{job_id}
Get crawl status and results (with optional page details).

**Request**:
```bash
GET /audit/site/550e8400-e29b-41d4-a716-446655440000?include_pages=true
```

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_pages` | boolean | true | Include detailed per-page data |

**Response (In Progress)**: `200 OK`
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "progress": {
    "crawled": 15,
    "queued": 45,
    "last_url": "https://example.com/page",
    "last_score": 82
  },
  "started_at": "2026-04-22T10:30:45.123456",
  "message": "Crawl in progress. Keep polling."
}
```

**Response (Completed)**: `200 OK`
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "started_at": "2026-04-22T10:30:45.123456",
  "completed_at": "2026-04-22T10:35:45.123456",
  "summary": {
    "total_pages_crawled": 45,
    "site_health_score": 75,
    "critical_issues": 2,
    "warning_issues": 15,
    "info_issues": 32,
    "total_crawl_time_seconds": 120
  },
  "aggregated_issues": [...],
  "pages": [...]
}
```

**Response (Failed)**: `200 OK`
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "failed",
  "error": "Connection timeout",
  "started_at": "2026-04-22T10:30:45.123456",
  "completed_at": "2026-04-22T10:33:12.654321"
}
```

---

#### 5. GET /audit/site/{job_id}/summary
Get just the summary (faster, no per-page data).

**Request**:
```bash
GET /audit/site/550e8400-e29b-41d4-a716-446655440000/summary
```

**Response**: `200 OK`
```json
{
  "status": "completed",
  "domain": "example.com",
  "summary": {
    "total_pages_crawled": 45,
    "site_health_score": 75,
    "critical_issues": 2,
    "warning_issues": 15,
    "info_issues": 32,
    "total_crawl_time_seconds": 120
  },
  "aggregated_issues": [...]
}
```

---

### Webhook Management Endpoints

#### 6. POST /webhook/register
Register a webhook for an existing job.

**Request**:
```bash
POST /webhook/register
Content-Type: application/json

{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "webhook_url": "https://your-frontend.com/webhook",
  "events": ["completed", "failed"]
}
```

**Parameters**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `job_id` | string | Yes | Job ID to attach webhook |
| `webhook_url` | string | Yes | Webhook endpoint URL |
| `events` | array | No | Events to trigger on (default: ["completed", "failed"]) |

**Response**: `200 OK`
```json
{
  "status": "registered",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "webhook_url": "https://your-frontend.com/webhook",
  "events": ["completed", "failed"]
}
```

---

#### 7. GET /webhook/list/{job_id}
List all webhooks registered for a job.

**Request**:
```bash
GET /webhook/list/550e8400-e29b-41d4-a716-446655440000
```

**Response**: `200 OK`
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "webhooks": [
    "https://your-frontend.com/webhook",
    "https://analytics.example.com/webhook"
  ],
  "count": 2
}
```

---

#### 8. DELETE /webhook/{job_id}/{webhook_url}
Unregister a specific webhook from a job.

**Request**:
```bash
DELETE /webhook/550e8400-e29b-41d4-a716-446655440000/https%3A%2F%2Fyour-frontend.com%2Fwebhook
```

**Response**: `200 OK`
```json
{
  "status": "unregistered",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "webhook_url": "https://your-frontend.com/webhook"
}
```

---

#### 9. DELETE /webhook/{job_id}
Clear all webhooks for a job.

**Request**:
```bash
DELETE /webhook/550e8400-e29b-41d4-a716-446655440000
```

**Response**: `200 OK`
```json
{
  "status": "cleared",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "cleared_count": 2
}
```

---

#### 10. POST /webhook/test
Test a webhook URL without needing a job.

**Request**:
```bash
POST /webhook/test
Content-Type: application/json

{
  "webhook_url": "https://your-frontend.com/webhook"
}
```

**Response**: `200 OK`
```json
{
  "status": "success",
  "webhook_url": "https://your-frontend.com/webhook",
  "response_code": 200,
  "message": "Test webhook sent successfully"
}
```

**Error Responses**:
- `408 Request Timeout` - Webhook took too long
- `502 Bad Gateway` - Could not connect
- `400 Bad Request` - Other errors

---

### Job Management Endpoints

#### 11. GET /jobs
List all crawl jobs in memory.

**Request**:
```bash
GET /jobs
```

**Response**: `200 OK`
```json
[
  {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "seed_url": "https://example.com",
    "status": "completed",
    "started_at": "2026-04-22T10:30:45.123456",
    "completed_at": "2026-04-22T10:35:45.123456",
    "progress": {
      "crawled": 45,
      "queued": 45
    }
  }
]
```

---

#### 12. DELETE /jobs
Clear all jobs from memory (for testing/debugging).

**Request**:
```bash
DELETE /jobs
```

**Response**: `200 OK`
```json
{
  "message": "All jobs cleared."
}
```

---

## 🔗 Webhook Payload Format

Your webhook endpoint will receive POST requests with this format:

```json
{
  "event": "completed",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "timestamp": "2026-04-22T10:35:45.123456",
  "data": {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "completed",
    "seed_url": "https://example.com",
    "summary": {
      "total_pages_crawled": 45,
      "site_health_score": 75,
      "critical_issues": 2,
      "warning_issues": 15,
      "info_issues": 32,
      "total_crawl_time_seconds": 120
    },
    "aggregated_issues": [
      {
        "issue_type": "Missing meta descriptions",
        "severity": "warning",
        "affected_count": 12,
        "recommendation": "Add unique meta descriptions"
      }
    ]
  }
}
```

### Expected Response
Your webhook should return `200 OK` with any JSON body (we only check status code):
```json
{
  "received": true,
  "processed": true
}
```

---

## 💡 Frontend Integration Example (React)

```javascript
// 1. Start a site crawl
const startCrawl = async (seedUrl) => {
  const response = await fetch('/audit/site', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      seed_url: seedUrl,
      max_pages: 50,
      webhook_url: 'https://your-frontend.com/api/webhook'
    })
  });
  
  const data = await response.json();
  const jobId = data.job_id;
  
  // Store jobId in state or context
  return jobId;
};

// 2. Handle webhook callback
app.post('/api/webhook', (req, res) => {
  const { event, job_id, data } = req.body;
  
  if (event === 'completed') {
    // Update frontend UI with results
    console.log('Crawl completed:', data.summary);
    // Push notification, update dashboard, etc.
  }
  
  res.json({ received: true });
});

// 3. Optional: Poll for progress if not using webhooks
const pollProgress = async (jobId) => {
  const response = await fetch(`/audit/site/${jobId}?include_pages=false`);
  const data = await response.json();
  
  if (data.status === 'running') {
    console.log(`Progress: ${data.progress.crawled}/${data.progress.queued}`);
    setTimeout(() => pollProgress(jobId), 5000); // Poll every 5s
  }
};
```

---

## 🔐 Error Codes Reference

| Code | Meaning | Example |
|------|---------|---------|
| `200` | Success | Job created, webhook sent |
| `400` | Bad Request | Invalid URL, missing field |
| `404` | Not Found | Job ID doesn't exist |
| `408` | Timeout | Webhook took too long |
| `500` | Server Error | Extraction failed |
| `502` | Bad Gateway | Failed to fetch URL |
| `503` | Service Unavailable | API overloaded |

---

## 📚 Documentation Links

- **Interactive Docs**: `GET /docs` (Swagger UI)
- **API Schema**: `GET /openapi.json`
- **ReDoc**: `GET /redoc`

---

**Last Updated**: 2026-04-22  
**API Status**: Production Ready ✅
