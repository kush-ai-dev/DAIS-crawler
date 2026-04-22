# DAIS Crawler - Multi-stage Docker build for Railway
FROM python:3.11-slim as base

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    apt-transport-https \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Chromium and dependencies for Playwright
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    libnss3 \
    libxss1 \
    libappindicator1 \
    libindicator7 \
    libxrandr2 \
    libxv1 \
    libxinerama1 \
    libxi6 \
    libgconf-2-4 \
    libgbm-dev \
    xdg-utils \
    fonts-liberation \
    libappindicator3-1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers in the Docker build
# This ensures the browsers are included in the final image
RUN playwright install --with-deps chromium

# Copy application code
COPY . .

# Create output directory
RUN mkdir -p output

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run the API server
CMD ["python", "-m", "api"]
