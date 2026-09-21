"""Shared-secret auth for deployments that must not be open.

This service holds a Nutrient license key and provider API keys (Anthropic,
OpenAI, Bedrock) and spends them on request, so an internet-reachable instance
with no caller check is an uncapped bill for whoever finds it.

The check is deliberately conditional on EXTRACTION_SERVICE_TOKEN being set:

- **Set** — every request must carry `Authorization: Bearer <token>`. This is
  the mode a private instance runs in, and the one the email extraction
  pipeline sample calls with.
- **Unset** — open, exactly as before. The browser-facing samples reach this
  service directly from the client via NEXT_PUBLIC_PYTHON_SDK_API_URL, and a
  token shipped to a browser is not a secret, so those deployments cannot use
  one. Requiring a token unconditionally would break all of them.

That conditional is a real hazard and worth naming: a private deployment that
forgets the variable is silently open rather than loudly broken. `warn_if_open`
exists to make that loud in the logs at startup, because the alternative —
failing closed when unset — would take every existing deployment down the first
time this shipped.
"""

import logging
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Unauthenticated by design: the platform health check runs before any caller
# has a token to present, and it reveals nothing but liveness.
PUBLIC_PATHS = frozenset({"/api/health"})


def _configured_token() -> str:
    # Read at call time, not import time, so tests can set the variable without
    # having to reimport the module.
    return os.environ.get("EXTRACTION_SERVICE_TOKEN", "")


def _presented_token(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() != "bearer" or not credentials:
        return None
    return credentials.strip()


class SharedSecretMiddleware(BaseHTTPMiddleware):
    """Require a bearer token when one is configured."""

    async def dispatch(self, request, call_next):
        expected = _configured_token()
        if not expected:
            return await call_next(request)

        # CORS preflight carries no Authorization header by design; rejecting it
        # would surface as an opaque CORS error rather than a 401.
        if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        presented = _presented_token(request.headers.get("authorization"))
        # compare_digest to keep the comparison constant-time; it needs str, so
        # the None case is handled before it rather than by passing "".
        if presented is None or not secrets.compare_digest(presented, expected):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        return await call_next(request)


def warn_if_open() -> None:
    """Log loudly when the service is reachable without a token."""
    if not _configured_token():
        logger.warning(
            "EXTRACTION_SERVICE_TOKEN is not set — this service accepts "
            "unauthenticated requests and will spend the configured Nutrient "
            "licence and provider API keys for any caller that reaches it. "
            "That is correct for a browser-facing sample deployment and wrong "
            "for anything else."
        )
