# 🚀 DAIS Crawler - Railway Deployment Guide

## Project Overview

**DAIS Crawler** is a production-ready SEO audit and crawling platform with:
- FastAPI REST server for remote site analysis
- Advanced multi-layer fetch strategy (HTTP → Playwright)
- Comprehensive SEO issue detection and reporting
- Background job processing for large site crawls
- CLI interface for local usage

### Technology Stack
- **Framework**: FastAPI + Uvicorn
- **Browser Automation**: Playwright (Chromium)
- **HTML Parsing**: BeautifulSoup4 + lxml
- **HTTP Client**: requests + curl-cffi
- **Data Validation**: Pydantic

---

## 📋 Railway Deployment Checklist

### ✅ Pre-Deployment Setup

1. **Repository Initialized**
   - Git repository created with all source code committed
   - `.gitignore` configured to exclude unnecessary files
   - `.dockerignore` optimized for smaller image builds

2. **Configuration Files**
   - ✅ `Procfile` - defines the start command
   - ✅ `runtime.txt` - specifies Python 3.11
   - ✅ `Dockerfile` - multi-stage Docker build with Playwright support
   - ✅ `railway.json` - Railway-specific configuration
   - ✅ `requirements.txt` - all dependencies pinned

3. **Entry Points**
   - ✅ `api/__init__.py` - package initialization
   - ✅ `api/__main__.py` - Uvicorn server launcher

---

## 🚄 Quick Start on Railway

### Step 1: Create Railway Project
```bash
# Install Railway CLI (optional, can also use UI)
npm i -g @railway/cli

# Login to Railway
railway login

# Create new project
railway init
```

### Step 2: Configure Environment Variables
In Railway Dashboard → Settings → Variables:

```env
# Optional - customize server behavior
HOST=0.0.0.0
PORT=8000
WORKERS=1

# Optional - for monitoring/logging
LOG_LEVEL=info
```

### Step 3: Deploy
**Option A: Using Railway CLI**
```bash
railway up
```

**Option B: Using Web UI**
1. Connect your GitHub repository
2. Railway auto-detects the `Dockerfile` 
3. Click "Deploy"

### Step 4: Verify Deployment
```bash
# Get the Railway URL
railway open

# Test health endpoint
curl https://your-railway-app.up.railway.app/health

# Check API docs
https://your-railway-app.up.railway.app/docs
```

---

## 📡 API Endpoints

Once deployed, the following endpoints are available:

### Single Page Audit
```bash
POST /audit/page
Body: {"url": "https://example.com"}
```

### Full Site Crawl (Async)
```bash
POST /audit/site
Body: {
  "seed_url": "https://example.com",
  "max_pages": 50,
  "respect_robots": true,
  "crawl_delay_ms": 500
}
```

### Check Crawl Progress
```bash
GET /audit/site/{job_id}
GET /audit/site/{job_id}/summary  # Faster, without page details
```

### API Documentation
- **Interactive Docs**: `https://your-app.up.railway.app/docs`
- **ReDoc**: `https://your-app.up.railway.app/redoc`

---

## ⚙️ Production Considerations

### 1. **Memory & Performance**
- Default: 1 Worker (suitable for development/MVP)
- For production: Increase workers based on expected concurrency
  ```env
  WORKERS=4  # Adjust based on Railway plan
  ```

### 2. **Job Storage (Critical!)**
⚠️ **Current Implementation**: In-memory job storage
- ✅ Fine for MVP and single-instance deployments
- ❌ Will lose jobs if service restarts
- ❌ Won't work with multiple replicas

**For Production Scale**: Migrate to persistent storage:
```python
# Options:
# 1. PostgreSQL (add via Railway)
# 2. Redis (for job queue + caching)
# 3. MongoDB (document storage)

# Recommended setup:
# - Use Celery for async job queue
# - Use Redis/PostgreSQL for persistent job status
```

### 3. **Output Storage**
Current: Local `/output/` directory
- ✅ Works for Railway (ephemeral filesystem)
- ⚠️ Files deleted when service restarts/redeploys

**For Production**: Use cloud storage:
```bash
# Option 1: Amazon S3
pip install boto3
# Configure AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_BUCKET

# Option 2: Google Cloud Storage
pip install google-cloud-storage
# Configure GCS credentials

# Option 3: Railway-provided PostgreSQL
# Store JSON reports in database
```

### 4. **Resource Scaling**
Railway pricing is based on:
- **CPU Hours**: Track Playwright browser usage
- **Memory**: Browsers consume 100-200MB per instance
- **Network**: Outbound crawl traffic

**Cost Optimization**:
```bash
# Monitor resource usage
railway logs

# Scale down when not in use
# Use Railway's auto-sleep feature for dev environments
```

### 5. **Timeouts & Limits**
Railway dyno timeout: 120 seconds (can't change)
- Page fetch: ~5-10 seconds per page
- Large site crawls: May need to chunk into batches
- Recommendation: Limit `max_pages` to 20-30 per crawl in production

### 6. **Browser Management**
The Dockerfile includes Playwright browser installation.
- Pre-installed: Chromium
- Cache location: `/root/.cache/ms-playwright`
- Size: ~300MB (included in image)

To add additional browsers:
```dockerfile
# In Dockerfile, modify:
RUN playwright install --with-deps chromium firefox
```

---

## 🔧 Deployment Architecture

```
┌─────────────────┐
│   GitHub        │
│   Repository    │
└────────┬────────┘
         │
         │ auto-detect Docker
         ↓
┌─────────────────────┐
│   Railway Build     │
│   - Install deps    │
│   - Install browsers│
│   - Build image     │
└────────┬────────────┘
         │
         ↓
┌────────────────────────────┐
│  Railway Container         │
│  - Python 3.11             │
│  - Playwright + Chromium   │
│  - FastAPI Server (uvicorn)│
└────────┬───────────────────┘
         │
         ↓
┌────────────────────┐
│  Public URL        │
│  (auto-assigned)   │
└────────────────────┘
```

---

## 📊 Monitoring & Logging

### Check Live Logs
```bash
railway logs --follow
```

### Key Metrics to Monitor
- Request latency (especially Playwright pages)
- Error rates (fetch failures, extraction issues)
- Memory usage (watch for browser leaks)
- Container restarts (indicates crashes)

### Common Issues

**Issue**: "Playwright browser not found"
- ✅ Fixed: Dockerfile includes `playwright install`

**Issue**: "Out of memory during site crawl"
- Solution: Reduce `max_pages` or increase Railway memory

**Issue**: "Job lost after restart"
- Expected: In-memory storage is ephemeral
- Solution: Migrate to persistent DB for production

---

## 🔐 Security Best Practices

1. **Environment Variables**
   - Never commit `.env` files
   - Use Railway's built-in secret management
   - Rotate credentials regularly

2. **CORS Configuration**
   - Current: Allow all origins (`["*"]`)
   - For production: Restrict to your domain
   ```python
   # In api/server.py
   allow_origins=["https://yourdomain.com"]
   ```

3. **Rate Limiting**
   - Not currently implemented
   - Consider adding for public API:
   ```bash
   pip install slowapi
   ```

4. **Input Validation**
   - Already implemented via Pydantic
   - URL scheme validation: auto-adds `https://`

---

## 📝 Local Development vs. Production

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run CLI
python run.py --site https://example.com

# Run API server
python -m api

# Access: http://localhost:8000
```

### Production (Railway)
```bash
# Automatically runs:
python -m api

# Accessible at:
https://your-app.up.railway.app
```

---

## 🚄 CI/CD Integration

### GitHub Actions Example
```yaml
name: Deploy to Railway

on:
  push:
    branches: [main, deploy]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: railway-app/railway-action@v1
        with:
          token: ${{ secrets.RAILWAY_TOKEN }}
          service: ${{ secrets.RAILWAY_SERVICE }}
          action: up
```

---

## 📚 Additional Resources

- [Railway Docs](https://docs.railway.app)
- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/)
- [Playwright Browser Management](https://playwright.dev/python/docs/browsers)
- [Uvicorn Configuration](https://www.uvicorn.org/)

---

## ⚡ Next Steps

1. **Test Locally**
   ```bash
   python -m api
   curl http://localhost:8000/health
   ```

2. **Push to GitHub**
   ```bash
   git add -A
   git commit -m "Add Railway deployment configuration"
   git push origin main
   ```

3. **Deploy via Railway**
   - Create Railway project
   - Connect GitHub repo
   - Deploy automatically

4. **Monitor & Optimize**
   - Check logs for errors
   - Adjust `WORKERS` based on load
   - Consider database migration for production

---

**Status**: ✅ Ready for Railway Deployment
**Last Updated**: 2026-04-22
