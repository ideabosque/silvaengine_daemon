# -*- coding: utf-8 -*-
"""Protocol-neutral daemon exception hierarchy.

These replace HTTP-framework exceptions so that business logic has zero
dependency on the transport layer. The gateway (``silvaengine_gateway``)
catches these and maps them to appropriate HTTP status codes.

Extracted from both ``a2a_daemon_engine.utils.exceptions`` and
``mcp_daemon_engine.utils.exceptions`` and renamed to neutral names
(``DaemonError`` instead of ``A2ADaemonError`` / ``MCPDaemonError``).
"""
from __future__ import annotations

__author__ = "bibow"


class DaemonError(Exception):
    """Base exception for all SilvaEngine daemon errors."""

    def __init__(self, message: str = "Daemon error") -> None:
        self.message = message
        super().__init__(message)


class AuthenticationError(DaemonError):
    """JWT verification failed or credentials are invalid."""

    def __init__(self, message: str = "Not authenticated") -> None:
        self.message = message
        super().__init__(message)


class TokenExpiredError(DaemonError):
    """JWT token has expired."""

    def __init__(self, message: str = "Token expired") -> None:
        self.message = message
        super().__init__(message)


class RateLimitExceeded(DaemonError):
    """Rate limit exceeded."""

    def __init__(self, message: str = "Rate limit exceeded") -> None:
        self.message = message
        super().__init__(message)


class InvalidRequestError(DaemonError):
    """Invalid request format or parameters."""

    def __init__(self, message: str = "Invalid request") -> None:
        self.message = message
        super().__init__(message)


__all__ = [
    "DaemonError",
    "AuthenticationError",
    "TokenExpiredError",
    "RateLimitExceeded",
    "InvalidRequestError",
]