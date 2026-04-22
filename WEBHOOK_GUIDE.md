# 🪝 Webhook Quick Reference

---

## What Are Webhooks?

Webhooks allow the DAIS Crawler API to **push notifications** to your frontend when a job completes, instead of you constantly polling for updates.

**Flow**:
```
Frontend sends crawl request
        ↓
API returns job_id immediately
        ↓
Crawl happens in background
        ↓
When complete → API sends webhook to your frontend
        ↓
Frontend receives notification automatically
```

---

## 🚀 5-Second Setup

### Step 1: Register webhook URL when starting crawl
```javascript
const response = await fetch('https://api.example.com/audit/site', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    seed_url: 'https://example.com',
    webhook_url: 'https://your-frontend.com/webhook'  // ← Add this
  })
});

const { job_id } = await response.json();
```

### Step 2: Create webhook endpoint
```javascript
// Next.js example
export async function POST(request) {
  const { event, data, status, job_id } = await request.json();
  
  if (status === 'completed') {
    console.log('Crawl done!', data.summary);
    // Update UI, save results, send notification, etc.
  }
  
  return new Response('OK', { status: 200 });
}
```

### Step 3: That's it!
Your endpoint will be called automatically when the crawl finishes.

---

## 📡 Webhook Payload

When your crawl completes, you'll receive:

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

---

## 🔑 Webhook Endpoints

### Register webhook (at start of crawl)
```bash
POST /audit/site
{
  "seed_url": "https://example.com",
  "webhook_url": "https://your-frontend.com/webhook"
}
```

### Register webhook (on existing job)
```bash
POST /webhook/register
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "webhook_url": "https://your-frontend.com/webhook"
}
```

### List webhooks for job
```bash
GET /webhook/list/{job_id}
```

### Remove webhook
```bash
DELETE /webhook/{job_id}/{webhook_url}
```

### Clear all webhooks for job
```bash
DELETE /webhook/{job_id}
```

### Test webhook
```bash
POST /webhook/test
{
  "webhook_url": "https://your-frontend.com/webhook"
}
```

---

## 💡 Common Patterns

### Pattern 1: Store results in database
```javascript
export async function POST(request) {
  const { job_id, data } = await request.json();
  
  await db.crawlResults.create({
    jobId: job_id,
    seedUrl: data.seed_url,
    summary: data.summary,
    issues: data.aggregated_issues,
  });
  
  return new Response('OK', { status: 200 });
}
```

### Pattern 2: Update real-time UI (WebSocket)
```javascript
export async function POST(request) {
  const { data } = await request.json();
  
  // Push update to all connected clients
  io.emit('crawl:completed', {
    jobId: data.job_id,
    score: data.summary.site_health_score,
  });
  
  return new Response('OK', { status: 200 });
}
```

### Pattern 3: Send notification
```javascript
import nodemailer from 'nodemailer';

export async function POST(request) {
  const { data } = await request.json();
  
  if (data.summary.critical_issues > 0) {
    // Alert user about critical issues
    await transporter.sendMail({
      to: 'user@example.com',
      subject: 'Critical SEO Issues Found',
      text: `${data.summary.critical_issues} critical issues detected`,
    });
  }
  
  return new Response('OK', { status: 200 });
}
```

### Pattern 4: Webhook + Polling hybrid
```javascript
// If webhook fails for some reason, fallback to polling
export async function POST(request) {
  const { job_id, data } = await request.json();
  
  try {
    // Store in real-time database
    await updateRealtimeDB(job_id, data);
  } catch (error) {
    // Fall back to polling on error
    schedulePolling(job_id);
  }
  
  return new Response('OK', { status: 200 });
}
```

---

## ⚠️ Webhook Requirements

Your webhook endpoint must:
- ✅ Return `200 OK` status code
- ✅ Respond within **10 seconds**
- ✅ Be publicly accessible (HTTPS preferred)
- ✅ Accept POST requests with JSON body
- ✅ Handle retries (API might send twice)

---

## 🧪 Testing Webhooks

### Option 1: Use /webhook/test endpoint
```bash
curl -X POST https://api.example.com/webhook/test \
  -H "Content-Type: application/json" \
  -d '{"webhook_url":"https://your-frontend.com/webhook"}'
```

### Option 2: Manual testing
```bash
# Send test payload to your endpoint
curl -X POST https://your-frontend.com/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event":"completed",
    "job_id":"test-123",
    "status":"completed",
    "timestamp":"2026-04-22T10:30:00Z",
    "data":{"summary":{"site_health_score":75}}
  }'
```

### Option 3: Use webhook.site
1. Go to https://webhook.site
2. Copy your unique URL
3. Use as webhook_url when starting crawl
4. Watch requests come in real-time

---

## 🐛 Webhook Debugging

### View test payload
```bash
POST /webhook/test

Response:
{
  "status": "success",
  "webhook_url": "...",
  "response_code": 200,
  "message": "Test webhook sent successfully"
}
```

### Check registered webhooks
```bash
GET /webhook/list/{job_id}

Response:
{
  "job_id": "...",
  "webhooks": [
    "https://your-frontend.com/webhook"
  ]
}
```

### Clear webhooks if stuck
```bash
DELETE /webhook/{job_id}

Response:
{
  "status": "cleared",
  "cleared_count": 1
}
```

---

## 📊 Webhook Events

Currently supported:
- `completed` - Crawl finished successfully
- `failed` - Crawl encountered an error

Future:
- `started` - Crawl began
- `progress` - Periodic progress updates
- `page_complete` - Individual page completed

---

## 🔒 Security Tips

### 1. Validate origin
```javascript
const CRAWLER_API = 'https://your-railway-app.up.railway.app';

export async function POST(request) {
  const origin = request.headers.get('origin');
  
  if (origin && !origin.includes('railway.app')) {
    return new Response('Forbidden', { status: 403 });
  }
  
  // Process webhook...
}
```

### 2. Use HTTPS only
Always use HTTPS for webhook URLs, never HTTP.

### 3. Timeout protection
Don't let webhook processing block your response:
```javascript
// Respond immediately
res.status(200).json({ received: true });

// Process async
setImmediate(() => {
  processWebhook(data);
});
```

### 4. Rate limiting
Implement idempotency to handle duplicate webhook calls:
```javascript
const processed = new Set(); // or use Redis

export async function POST(request) {
  const { job_id } = await request.json();
  
  if (processed.has(job_id)) {
    return new Response('Already processed', { status: 200 });
  }
  
  processed.add(job_id);
  // Process...
}
```

---

## 🚀 Production Checklist

Before going live:
- [ ] Webhook endpoint returns 200 OK
- [ ] Endpoint is HTTPS
- [ ] Timeout is < 10 seconds
- [ ] Handles duplicate calls
- [ ] Validates payloads
- [ ] Logs all received webhooks
- [ ] Has error handling
- [ ] Tested with /webhook/test
- [ ] Database can store results
- [ ] Monitoring/alerts set up

---

## 📈 Example: Complete Workflow

```javascript
// 1. Start crawl with webhook
const response = await fetch('https://api.example.com/audit/site', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    seed_url: 'https://example.com',
    max_pages: 50,
    webhook_url: 'https://my-frontend.com/api/webhook'
  })
});

const { job_id } = await response.json();
console.log('Crawl started:', job_id);

// 2. User sees loading state
updateUI({ status: 'loading', message: 'Crawling...' });

// 3. Seconds later... API calls webhook
// POST /api/webhook with results

// 4. Update UI with results
updateUI({ 
  status: 'completed',
  score: 75,
  issues: 12
});
```

---

**Webhooks make your frontend feel instant!** ⚡
