from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_seconds: int


class RateLimiter:
    """
    Simple in-memory, fixed-window rate limiter.

    The key is based on the client IP and endpoint. This will be replaced 
    with a Postgres-backed implementation later without changing 
    the middleware interface.
    """

    def __init__(
        self,
        default_limit: int = 60,
        default_window_seconds: int = 60,
    ) -> None:
        self.default_rule = RateLimitRule(
            limit=default_limit,
            window_seconds=default_window_seconds,
        )
        self.rules: dict[str, RateLimitRule] = {}
        self.requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    def add_rule(
        self,
        path: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        if window_seconds <= 0:
            raise ValueError("window_seconds must be greater than zero")

        self.rules[path] = RateLimitRule(
            limit=limit,
            window_seconds=window_seconds,
        )

    def get_rule(self, path: str) -> RateLimitRule:
        return self.rules.get(path, self.default_rule)

    async def check(self, key: str, rule: RateLimitRule) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - rule.window_seconds

        async with self._lock:
            timestamps = self.requests[key]

            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= rule.limit:
                retry_after = max(
                    1,
                    int(rule.window_seconds - (now - timestamps[0])),
                )
                return False, retry_after

            timestamps.append(now)

            return True, 0

    async def cleanup(self) -> None:
        """
        Remove stale keys so the in-memory dictionary doesn't grow forever.

        This can be called periodically by the application if desired.
        """
        now = time.monotonic()

        async with self._lock:
            empty_keys: list[str] = []

            for key, timestamps in self.requests.items():
                rule = self.get_rule(key.split(":", 1)[-1])
                cutoff = now - rule.window_seconds

                while timestamps and timestamps[0] <= cutoff:
                    timestamps.popleft()

                if not timestamps:
                    empty_keys.append(key)

            for key in empty_keys:
                self.requests.pop(key, None)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    General per-endpoint rate limiting.

    Requests are identified by:

        client IP + request path

    This provides a general baseline protection for every endpoint.

    Specific endpoint limits can be configured with:

        limiter.add_rule(
            "/api/v1/agent/runs",
            limit=10,
            window_seconds=60,
        )

    Phase 7 will have to configure the tighter agent-run limit without changing
    this middleware.
    """

    def __init__(
        self,
        app,
        limiter: RateLimiter | None = None,
        excluded_paths: set[str] | None = None,
    ) -> None:
        super().__init__(app)

        self.limiter = limiter or RateLimiter()
        self.excluded_paths = excluded_paths or {
            "/health",
            "/ready",
        }

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        client = request.client

        if client is None:
            return "unknown"

        return client.host

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ):
        path = request.url.path

        if path in self.excluded_paths:
            return await call_next(request)

        rule = self.limiter.get_rule(path)
        client_ip = self._get_client_ip(request)
        key = f"{client_ip}:{path}"

        allowed, retry_after = await self.limiter.check(key, rule)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please try again later."
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(rule.limit),
                },
            )

        response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(rule.limit)

        return response