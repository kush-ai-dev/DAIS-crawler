# DAIS Crawler - Docker build for Railway
# Using official Python base with all build tools
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for Playwright and build tools
# Kept minimal to reduce image size
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    wget \
    # Required for Playwright Chromium
    libc6 \
    libstdc++6 \
    libx11-6 \
    libxcb1 \
    libxext6 \
    libxrender1 \
    libnss3 \
    libgconf-2-4 \
    libxss1 \
    fonts-liberation \
    libappindicator1 \
    libxrandr2 \
    libgbm1 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
# Uses Playwright's built-in browser installation which handles all dependencies
RUN python -m playwright install chromium

# Copy application code
COPY . .

# Create output directory for reports
RUN mkdir -p output

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=5)" || exit 1

# Expose port for Railway
EXPOSE 8000

# Run the API server
CMD ["python", "-m", "api"]
