# 🎨 Lovable Frontend Integration Guide

Quick setup guide to integrate DAIS Crawler API with your Lovable application.

---

## ✅ Prerequisites

- Lovable project initialized
- DAIS Crawler API deployed on Railway
- API base URL available (e.g., `https://your-app.up.railway.app`)

---

## 🚀 Quick Integration (5 minutes)

### Step 1: Create API Client

**File**: `src/lib/api/crawler.ts`

```typescript
const API_BASE = process.env.REACT_APP_CRAWLER_API || 'https://your-app.up.railway.app';

export interface CrawlRequest {
  seed_url: string;
  max_pages?: number;
  respect_robots?: boolean;
  crawl_delay_ms?: number;
  webhook_url?: string;
}

export interface PageAuditRequest {
  url: string;
  force_playwright?: boolean;
  webhook_url?: string;
}

// Single page audit
export async function auditPage(request: PageAuditRequest) {
  const response = await fetch(`${API_BASE}/audit/page`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail?.error || 'Audit failed');
  }

  return response.json();
}

// Start site crawl
export async function startSiteCrawl(request: CrawlRequest) {
  const response = await fetch(`${API_BASE}/audit/site`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail?.error || 'Crawl failed');
  }

  return response.json();
}

// Get crawl status
export async function getCrawlStatus(jobId: string, includePages = false) {
  const url = new URL(`${API_BASE}/audit/site/${jobId}`);
  url.searchParams.set('include_pages', String(includePages));

  const response = await fetch(url.toString());

  if (!response.ok) {
    throw new Error('Failed to get crawl status');
  }

  return response.json();
}

// Get crawl summary (faster)
export async function getCrawlSummary(jobId: string) {
  const response = await fetch(`${API_BASE}/audit/site/${jobId}/summary`);

  if (!response.ok) {
    throw new Error('Failed to get crawl summary');
  }

  return response.json();
}

// Register webhook
export async function registerWebhook(jobId: string, webhookUrl: string) {
  const response = await fetch(`${API_BASE}/webhook/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      job_id: jobId,
      webhook_url: webhookUrl,
      events: ['completed', 'failed'],
    }),
  });

  return response.json();
}

// Health check
export async function checkHealth() {
  const response = await fetch(`${API_BASE}/health`);
  return response.ok;
}
```

### Step 2: Create React Hook

**File**: `src/hooks/useCrawler.ts`

```typescript
import { useState, useCallback } from 'react';
import {
  auditPage,
  startSiteCrawl,
  getCrawlStatus,
  getCrawlSummary,
  registerWebhook,
  PageAuditRequest,
  CrawlRequest,
} from '@/lib/api/crawler';

interface CrawlState {
  jobId: string | null;
  status: 'idle' | 'loading' | 'running' | 'completed' | 'failed';
  progress: { crawled: number; queued: number };
  result: any;
  error: string | null;
}

export function useCrawler() {
  const [state, setState] = useState<CrawlState>({
    jobId: null,
    status: 'idle',
    progress: { crawled: 0, queued: 0 },
    result: null,
    error: null,
  });

  // Single page audit
  const auditSinglePage = useCallback(async (request: PageAuditRequest) => {
    setState(prev => ({ ...prev, status: 'loading', error: null }));
    try {
      const result = await auditPage(request);
      setState(prev => ({
        ...prev,
        status: 'completed',
        result,
      }));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      setState(prev => ({
        ...prev,
        status: 'failed',
        error: message,
      }));
      throw error;
    }
  }, []);

  // Start site crawl
  const startCrawl = useCallback(async (request: CrawlRequest) => {
    setState(prev => ({ ...prev, status: 'loading', error: null }));
    try {
      const response = await startSiteCrawl(request);
      
      // Register webhook if provided
      if (request.webhook_url) {
        await registerWebhook(response.job_id, request.webhook_url);
      }

      setState(prev => ({
        ...prev,
        jobId: response.job_id,
        status: 'running',
      }));

      // Start polling
      pollStatus(response.job_id);

      return response;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      setState(prev => ({
        ...prev,
        status: 'failed',
        error: message,
      }));
      throw error;
    }
  }, []);

  // Poll crawl status
  const pollStatus = useCallback(async (jobId: string) => {
    try {
      const response = await getCrawlSummary(jobId);

      if (response.status === 'completed' || response.status === 'failed') {
        setState(prev => ({
          ...prev,
          status: response.status as any,
          result: response,
          jobId,
        }));
      } else if (response.status === 'running') {
        setState(prev => ({
          ...prev,
          progress: response.progress || prev.progress,
          jobId,
        }));
        // Poll again after 5 seconds
        setTimeout(() => pollStatus(jobId), 5000);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Poll failed';
      setState(prev => ({
        ...prev,
        status: 'failed',
        error: message,
      }));
    }
  }, []);

  const reset = useCallback(() => {
    setState({
      jobId: null,
      status: 'idle',
      progress: { crawled: 0, queued: 0 },
      result: null,
      error: null,
    });
  }, []);

  return {
    ...state,
    auditSinglePage,
    startCrawl,
    pollStatus,
    reset,
  };
}
```

### Step 3: Create Crawler Component

**File**: `src/components/CrawlerForm.tsx`

```tsx
'use client';

import { useState } from 'react';
import { useCrawler } from '@/hooks/useCrawler';

export function CrawlerForm() {
  const [seedUrl, setSeedUrl] = useState('https://example.com');
  const [maxPages, setMaxPages] = useState(50);
  const crawler = useCrawler();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    crawler.startCrawl({
      seed_url: seedUrl,
      max_pages: maxPages,
      webhook_url: `${window.location.origin}/api/crawler-webhook`,
    });
  };

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">SEO Site Crawler</h1>

      {crawler.status === 'idle' || crawler.status === 'completed' || crawler.status === 'failed' ? (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">Website URL</label>
            <input
              type="url"
              value={seedUrl}
              onChange={(e) => setSeedUrl(e.target.value)}
              placeholder="https://example.com"
              className="w-full px-4 py-2 border rounded-lg"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">Max Pages</label>
            <input
              type="number"
              value={maxPages}
              onChange={(e) => setMaxPages(Number(e.target.value))}
              min={1}
              max={500}
              className="w-full px-4 py-2 border rounded-lg"
            />
          </div>

          <button
            type="submit"
            disabled={crawler.status === 'loading'}
            className="w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {crawler.status === 'loading' ? 'Starting...' : 'Start Crawl'}
          </button>

          {crawler.error && (
            <div className="p-4 bg-red-100 text-red-700 rounded-lg">
              {crawler.error}
            </div>
          )}
        </form>
      ) : null}

      {crawler.status === 'running' && (
        <div className="space-y-4">
          <div className="p-4 bg-blue-50 rounded-lg">
            <h2 className="font-semibold mb-2">Crawling in Progress</h2>
            <p>Progress: {crawler.progress.crawled} / {crawler.progress.queued} pages</p>
            <div className="w-full bg-gray-200 rounded-full h-2 mt-2">
              <div
                className="bg-blue-600 h-2 rounded-full transition-all"
                style={{
                  width: `${
                    crawler.progress.queued > 0
                      ? (crawler.progress.crawled / crawler.progress.queued) * 100
                      : 0
                  }%`,
                }}
              />
            </div>
          </div>
        </div>
      )}

      {crawler.status === 'completed' && crawler.result && (
        <div className="space-y-4">
          <div className="p-4 bg-green-50 rounded-lg">
            <h2 className="font-semibold text-green-900">✓ Crawl Completed</h2>
            <p className="text-sm text-green-700 mt-1">
              {crawler.result.summary?.total_pages_crawled} pages crawled in{' '}
              {crawler.result.summary?.total_crawl_time_seconds}s
            </p>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div className="p-4 border rounded-lg">
              <div className="text-3xl font-bold">
                {crawler.result.summary?.site_health_score}
              </div>
              <div className="text-sm text-gray-600">Health Score</div>
            </div>
            <div className="p-4 border rounded-lg">
              <div className="text-2xl font-bold text-red-600">
                {crawler.result.summary?.critical_issues}
              </div>
              <div className="text-sm text-gray-600">Critical Issues</div>
            </div>
            <div className="p-4 border rounded-lg">
              <div className="text-2xl font-bold text-yellow-600">
                {crawler.result.summary?.warning_issues}
              </div>
              <div className="text-sm text-gray-600">Warnings</div>
            </div>
          </div>

          <button
            onClick={crawler.reset}
            className="w-full bg-gray-200 py-2 rounded-lg hover:bg-gray-300"
          >
            Start New Crawl
          </button>
        </div>
      )}

      {crawler.status === 'failed' && (
        <div className="p-4 bg-red-50 rounded-lg">
          <h2 className="font-semibold text-red-900">✗ Crawl Failed</h2>
          <p className="text-sm text-red-700 mt-1">{crawler.error}</p>
          <button
            onClick={crawler.reset}
            className="w-full bg-red-200 py-2 rounded-lg mt-4 hover:bg-red-300"
          >
            Try Again
          </button>
        </div>
      )}
    </div>
  );
}
```

### Step 4: Create Webhook Endpoint

**File**: `src/app/api/crawler-webhook/route.ts`

```typescript
import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  const payload = await request.json();

  // Handle webhook payload
  console.log('Crawler webhook received:', {
    event: payload.event,
    jobId: payload.job_id,
    status: payload.status,
  });

  // TODO: Update your database or state management with results
  // - Store job results
  // - Update UI
  // - Send notifications
  // - etc.

  return NextResponse.json({ received: true });
}
```

### Step 5: Environment Setup

**File**: `.env.local`

```env
REACT_APP_CRAWLER_API=https://your-railway-app.up.railway.app
```

---

## 🔧 Component Usage

```tsx
import { CrawlerForm } from '@/components/CrawlerForm';

export default function Home() {
  return (
    <main>
      <CrawlerForm />
    </main>
  );
}
```

---

## 📊 Webhook Handling (Next.js)

For advanced webhook handling with database persistence:

```typescript
// src/app/api/crawler-webhook/route.ts
import { db } from '@/lib/db'; // Your database
import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  const webhook = await request.json();

  try {
    // Save results to database
    await db.crawlResults.create({
      jobId: webhook.job_id,
      seedUrl: webhook.data.seed_url,
      status: webhook.status,
      summary: webhook.data.summary,
      issues: webhook.data.aggregated_issues,
      completedAt: new Date(webhook.timestamp),
    });

    // Optionally trigger notifications
    if (webhook.event === 'completed') {
      // Send Slack notification, email, etc.
      await notifyCompletion(webhook.data);
    }

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Webhook processing failed:', error);
    return NextResponse.json(
      { error: 'Processing failed' },
      { status: 500 }
    );
  }
}
```

---

## 🎯 Real-Time Updates (WebSocket Alternative)

If webhooks aren't sufficient, poll the API:

```typescript
// Hook for real-time polling
export function useLiveProgress(jobId: string | null) {
  const [progress, setProgress] = useState<any>(null);

  useEffect(() => {
    if (!jobId) return;

    const interval = setInterval(async () => {
      try {
        const status = await getCrawlSummary(jobId);
        setProgress(status);

        if (status.status !== 'running') {
          clearInterval(interval);
        }
      } catch (error) {
        console.error('Poll failed:', error);
      }
    }, 3000); // Poll every 3 seconds

    return () => clearInterval(interval);
  }, [jobId]);

  return progress;
}
```

---

## 🧪 Testing

```typescript
// src/__tests__/crawler.test.ts
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CrawlerForm } from '@/components/CrawlerForm';

describe('CrawlerForm', () => {
  it('submits crawl request', async () => {
    render(<CrawlerForm />);

    fireEvent.change(
      screen.getByPlaceholderText('https://example.com'),
      { target: { value: 'https://example.com' } }
    );

    fireEvent.click(screen.getByText('Start Crawl'));

    await waitFor(() => {
      expect(screen.getByText(/Crawling in Progress/i)).toBeInTheDocument();
    });
  });
});
```

---

## 🚀 Deployment Checklist

- [ ] Environment variable set: `REACT_APP_CRAWLER_API`
- [ ] API health check passing: `GET /health`
- [ ] Webhook endpoint configured
- [ ] Error handling implemented
- [ ] Loading states visible
- [ ] Results persisted to database
- [ ] Tests passing

---

## 📚 Additional Resources

- [API Documentation](./API_ENDPOINTS.md)
- [Railway Deployment](./RAILWAY_DEPLOYMENT.md)
- [Lovable Docs](https://docs.lovable.dev)

---

**Ready to integrate!** ✅
