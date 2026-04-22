# ✅ Railway Deployment Checklist

## Pre-Deployment Verification

### 1. Repository & Git
- [ ] Repository initialized: `git init`
- [ ] All files committed: `git status` shows clean
- [ ] `.gitignore` properly configured
- [ ] No secrets in committed code
- [ ] `.git/` folder included in repo

### 2. Configuration Files
- [ ] ✅ `Procfile` exists with correct start command
- [ ] ✅ `runtime.txt` specifies Python 3.11
- [ ] ✅ `Dockerfile` present and valid
- [ ] ✅ `.dockerignore` configured
- [ ] ✅ `railway.json` added
- [ ] [ ] `.env.example` created (optional, for documentation)

### 3. Application Code
- [ ] ✅ `api/__init__.py` exists
- [ ] ✅ `api/__main__.py` exists with Uvicorn entry point
- [ ] [ ] No hardcoded localhost URLs
- [ ] [ ] No hardcoded port numbers (use `os.getenv("PORT")`)
- [ ] [ ] Error handling for missing env vars

### 4. Dependencies
- [ ] ✅ `requirements.txt` up-to-date with all packages
- [ ] [ ] Versions pinned (not `package` but `package==1.2.3`)
- [ ] [ ] No duplicate entries
- [ ] [ ] `uvicorn[standard]` included

### 5. Docker Build Test (Optional but Recommended)
```bash
# Test Docker build locally
docker build -t dais-crawler .

# Should complete without errors
# Should be < 2GB in size
```

### 6. Code Quality
- [ ] [ ] No syntax errors: `python -m py_compile api/server.py`
- [ ] [ ] No import errors: `python -c "import api.server"`
- [ ] [ ] FastAPI app starts: `python -m api`
- [ ] [ ] Health endpoint responds: `curl http://localhost:8000/health`

### 7. Environment Variables
- [ ] [ ] Identified all required env vars
- [ ] [ ] Documented them in `RAILWAY_DEPLOYMENT.md`
- [ ] [ ] No hardcoded secrets in code
- [ ] [ ] Using `os.getenv()` for all env-specific config

### 8. Documentation
- [ ] ✅ `RAILWAY_DEPLOYMENT.md` comprehensive guide
- [ ] ✅ `PRODUCTION_GUIDE.md` architecture & scaling
- [ ] [ ] README.md updated with Railway link (optional)

---

## Deployment Steps

### Step 1: Prepare GitHub
```bash
# Ensure all changes committed
git add -A
git commit -m "Add Railway deployment configuration"
git push origin main
```

### Step 2: Create Railway Project
```bash
# Option A: Using Railway CLI
npm i -g @railway/cli
railway login
railway init

# Option B: Using Web UI
# Visit https://railway.app
# Click "Create Project"
# Select "Deploy from GitHub"
# Select your repository
```

### Step 3: Configure Environment (in Railway Dashboard)
```
Settings → Variables

No required variables for MVP, but optional:
HOST=0.0.0.0        (usually auto-set)
PORT=8000           (usually auto-set)
WORKERS=1           (increase for higher traffic)
LOG_LEVEL=info
```

### Step 4: Deploy
```bash
# Via CLI
railway up

# Via Web UI
# Click "Deploy" button (auto-deploys on git push)
```

### Step 5: Verify Deployment
```bash
# Get app URL
railway open

# Test endpoints
curl https://[your-app].up.railway.app/health
curl https://[your-app].up.railway.app/docs

# Expected responses:
# GET /health     → {"status":"ok","service":"DAIS Crawler API",...}
# GET /docs       → OpenAPI documentation page
```

---

## Post-Deployment Checks

### Check Logs
```bash
railway logs --follow
```

**Look for**:
- ✅ No import errors
- ✅ No module not found errors  
- ✅ "Application startup complete" message
- ✅ No Playwright installation failures

### Test API
```bash
# Health check
curl https://[your-app].up.railway.app/health

# Example page audit
curl -X POST https://[your-app].up.railway.app/audit/page \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com"}'

# Expected: JSON report with audit results
```

### Monitor Resources
```bash
# Check in Railway Dashboard
Settings → Analytics

Watch for:
- CPU usage (should be low at idle)
- Memory usage (< 500MB is healthy)
- Network ingress/egress
- Request count
```

---

## Common Issues & Fixes

### Issue: "Port already in use"
**Cause**: Railway auto-assigns PORT env var
**Fix**: Ensure code uses: `port = int(os.getenv("PORT", 8000))`

### Issue: "Module not found: playwright"
**Cause**: Dockerfile didn't install requirements
**Fix**: Ensure `COPY requirements.txt .` and `pip install` in Dockerfile

### Issue: "Playwright browser not found"  
**Cause**: Dockerfile didn't run `playwright install`
**Fix**: Dockerfile already includes this, but verify:
```dockerfile
RUN playwright install --with-deps chromium
```

### Issue: "Connection refused" to localhost
**Cause**: Trying to connect to localhost from another service
**Fix**: Use actual service URL, not localhost

### Issue: "App crashes after 120 seconds"
**Cause**: Long-running requests timeout on Railway
**Fix**: Implement async operations or return job_id for background tasks

### Issue: "Chromium too large" (build fails)
**Cause**: Dockerfile image exceeds Railway limits
**Fix**: Use lightweight base image:
```dockerfile
FROM python:3.11-slim  # Already using slim
```

### Issue: "Memory keeps growing"
**Cause**: Browser processes not cleaned up properly
**Fix**: Ensure browser.close() called in finally blocks

---

## Rollback Procedure

If deployment fails:

```bash
# Via CLI
railway down

# Via Web UI
Settings → Danger Zone → Delete Deployment

# Then fix and redeploy
git commit -am "Fix: [issue]"
git push origin main
railway up  # or click Deploy again
```

---

## Production Monitoring Checklist

### Daily Checks
- [ ] Zero error logs (or only expected errors)
- [ ] Response time < 10 seconds for most requests
- [ ] Memory usage stable (not growing)
- [ ] CPU usage < 50% at idle

### Weekly Checks  
- [ ] Review error patterns
- [ ] Check resource costs
- [ ] Test each API endpoint manually
- [ ] Review logs for slowdown patterns

### Monthly Checks
- [ ] Review usage metrics
- [ ] Plan capacity upgrades if needed
- [ ] Update dependencies if critical patches available
- [ ] Document any scaling decisions

---

## Success Indicators ✅

Your deployment is successful when:

1. **Health**: `GET /health` returns 200 OK
2. **API Docs**: `GET /docs` shows OpenAPI interface
3. **Page Audit**: `POST /audit/page` completes in < 15s
4. **Site Crawl**: `POST /audit/site` returns job_id immediately
5. **Monitoring**: Logs show no errors or warnings
6. **Performance**: Response times stable and predictable
7. **Resources**: Memory < 500MB, CPU idle when not processing

---

## Support Resources

- **Railway Docs**: https://docs.railway.app
- **FastAPI Docs**: https://fastapi.tiangolo.com
- **Playwright Docs**: https://playwright.dev/python
- **GitHub Issues**: Open issues on your repo for tracking

---

## Next Steps After Successful Deployment

1. **Share API URL** with stakeholders
2. **Get Feedback** from real users
3. **Monitor Usage** patterns
4. **Plan Phase 2** upgrades if needed:
   - Add database
   - Add rate limiting
   - Implement persistent job storage
   - Scale to multiple workers

---

**Last Verified**: 2026-04-22  
**Status**: Ready to Deploy ✅

---

## Quick Start Command (Copy & Paste)

```bash
# Clone and deploy
git clone https://github.com/[your]/DAIS-crawler.git
cd DAIS-crawler
railway init
railway up
railway open

# Test (once deployed)
curl $(railway open)/health
```

---

**🚀 You're ready to deploy to Railway!**
