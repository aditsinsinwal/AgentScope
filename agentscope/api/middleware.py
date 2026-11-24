"""Pure-ASGI middleware: request ids, bearer auth, body-size limit, safe 500s.

Written as raw ASGI (not ``BaseHTTPMiddleware``) so the body limit also applies to chunked
uploads and so streaming/lifespan behaviour is untouched.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("agentscope.api")

PUBLIC_PATHS = frozenset({"/api/v1/health"})
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def safe_request_id(candidate: str | None) -> str:
    """Honour an incoming id only when it is a short, log-safe token."""
    if candidate and _SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


def error_envelope(
    code: str, message: str, request_id: str | None, details: Any = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if details is not None:
        body["details"] = details
    return body


def warn_if_unauthenticated(host: str, token: str | None) -> bool:
    """Log one warning when listening beyond loopback without a token. Returns whether it warned."""
    if token or host in LOOPBACK_HOSTS:
        return False
    logger.warning(
        "AgentScope API is binding to %s without AGENTSCOPE_API_TOKEN; "
        "anyone who can reach this port can start runs and read traces.",
        host,
    )
    return True


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, *, api_token: str | None, max_request_bytes: int) -> None:
        self.app = app
        self._token = api_token.encode() if api_token else None
        self._max_bytes = max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope["headers"]}
        request_id = safe_request_id(headers.get(b"x-request-id", b"").decode("latin-1") or None)
        scope.setdefault("state", {})["request_id"] = request_id
        started = False

        overflow = False
        suppress = False

        async def emit(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message = {
                    **message,
                    "headers": [
                        (k, v)
                        for k, v in message.get("headers", [])
                        if k.lower() != b"x-request-id"
                    ]
                    + [(b"x-request-id", request_id.encode())],
                }
            await send(message)

        async def send_with_id(message: Message) -> None:
            nonlocal suppress
            if suppress:
                return
            if overflow and message["type"] == "http.response.start":
                # The framework may already have turned the truncated body into a 400/422;
                # the real cause is the size limit, so replace its response.
                suppress = True
                await reject(
                    413, "payload_too_large", f"request body exceeds {self._max_bytes} bytes"
                )
                return
            await emit(message)

        async def reject(
            status: int, code: str, message: str, extra: list[Any] | None = None
        ) -> None:
            body = json.dumps(error_envelope(code, message, request_id)).encode()
            await emit(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        *(extra or []),
                    ],
                }
            )
            await emit({"type": "http.response.body", "body": body})

        path: str = scope["path"]
        if self._token is not None and path.startswith("/api/") and path not in PUBLIC_PATHS:
            supplied = headers.get(b"authorization", b"")
            scheme, _, credential = supplied.partition(b" ")
            if scheme.lower() != b"bearer" or not hmac.compare_digest(
                credential.strip(), self._token
            ):
                await reject(
                    401,
                    "unauthorized",
                    "missing or invalid bearer token",
                    [(b"www-authenticate", b"Bearer")],
                )
                return

        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self._max_bytes:
            await reject(413, "payload_too_large", f"request body exceeds {self._max_bytes} bytes")
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received, overflow
            if overflow:
                return {"type": "http.request", "body": b"", "more_body": False}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    overflow = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        try:
            await self.app(scope, limited_receive, send_with_id)
        except Exception:
            logger.exception(
                "unhandled error request_id=%s %s %s", request_id, scope["method"], path
            )
            if not started:
                await reject(500, "internal_error", "internal server error")
