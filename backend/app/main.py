from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings
from app.middleware.csrf import CSRFMiddleware
from app.middleware.rate_limit import RateLimitMiddleware, RateLimiter


app = FastAPI(
    title="Workspace AI Agent",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_allowed_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.add_middleware(CSRFMiddleware)

rate_limiter = RateLimiter(
    default_limit=60,
    default_window_seconds=60,
)


app.add_middleware(
    RateLimitMiddleware,
    limiter=rate_limiter,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    return {"status": "ready"}