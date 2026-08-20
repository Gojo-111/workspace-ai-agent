import secrets
from hmac import compare_digest

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config.settings import settings


CSRF_COOKIE_NAME = "waa_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
SESSION_COOKIE_NAME = "waa_session"

STATE_CHANGING_METHODS = {"POST", "PATCH", "DELETE"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Protect cookie-authenticated state-changing requests against CSRF.

    Uses the double-submit cookie pattern:
    - The backend issues a random CSRF token in a readable cookie.
    - The frontend reads that cookie and sends the same value in
      X-CSRF-Token.
    - The backend compares the two values before allowing the request through.

    The authentication session cookie remains HttpOnly.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)

        if not csrf_cookie:
            csrf_cookie = secrets.token_urlsafe(32)

        session_cookie = request.cookies.get(SESSION_COOKIE_NAME)

        if request.method in STATE_CHANGING_METHODS and session_cookie:
            csrf_header = request.headers.get(CSRF_HEADER_NAME)

            if not csrf_header or not compare_digest(
                csrf_cookie,
                csrf_header,
            ):
                return Response(
                    content='{"detail":"CSRF validation failed"}',
                    status_code=403,
                    media_type="application/json",
                )

        response = await call_next(request)

        if CSRF_COOKIE_NAME not in request.cookies:
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=csrf_cookie,
                httponly=False,
                secure=settings.cookie_secure,
                samesite=settings.cookie_samesite,
            )

        return response