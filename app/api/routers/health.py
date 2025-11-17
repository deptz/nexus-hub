"""Health check API router."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.infra.database import get_db
from app.infra.metrics import get_metrics_response

router = APIRouter()


@router.get("/health", tags=["Health"])
async def health_check():
    """Combined health check endpoint."""
    return {
        "status": "ok",
        "service": "nexus-hub",
        "version": "1.0.0",
    }


@router.get("/health/live", tags=["Health"])
async def liveness_probe():
    """Liveness probe - indicates if the process is running."""
    return {"status": "alive"}


@router.get("/health/ready", tags=["Health"])
async def readiness_probe(db: Session = Depends(get_db)):
    """Readiness probe - checks database connectivity."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        return {"status": "not_ready"}, 503


@router.get("/metrics", tags=["Health"])
async def metrics():
    """Prometheus metrics endpoint."""
    return get_metrics_response()

