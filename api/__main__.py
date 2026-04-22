"""
DAIS Crawler API - Entry point for Uvicorn server
Allows running with: python -m api.server
"""

import os
import sys
import uvicorn

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ == "__main__":
    # Get configuration from environment variables
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    workers = int(os.getenv("WORKERS", 1))
    
    # For Railway, use port from $PORT environment variable
    if "RAILWAY_ENVIRONMENT_NAME" in os.environ:
        port = int(os.getenv("PORT", 8000))
    
    uvicorn.run(
        "api.server:app",
        host=host,
        port=port,
        workers=workers,
        reload=False,
        log_level="info",
    )
