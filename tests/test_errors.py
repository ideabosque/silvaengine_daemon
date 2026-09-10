# -*- coding: utf-8 -*-
"""Unit tests for ``silvaengine_daemon.errors``.

Tests cover the exception hierarchy, default messages, and custom messages.
"""
from __future__ import annotations

__author__ = "bibow"

import pytest

from silvaengine_daemon.errors import (
    DaemonError,
    AuthenticationError,
    TokenExpiredError,
    RateLimitExceeded,
    InvalidRequestError,
)


class TestExceptionHierarchy:
    """Tests for the exception hierarchy structure."""

    def test_daemon_error_is_base(self) -> None:
        """DaemonError is the base for all daemon exceptions."""
        assert issubclass(AuthenticationError, DaemonError)
        assert issubclass(TokenExpiredError, DaemonError)
        assert issubclass(RateLimitExceeded, DaemonError)
        assert issubclass(InvalidRequestError, DaemonError)

    def test_daemon_error_is_exception(self) -> None:
        """DaemonError extends Exception."""
        assert issubclass(DaemonError, Exception)

    def test_all_distinct(self) -> None:
        """All exception classes are distinct."""
        classes = {
            AuthenticationError,
            TokenExpiredError,
            RateLimitExceeded,
            InvalidRequestError,
        }
        assert len(classes) == 4


class TestDefaultMessages:
    """Tests for default message values."""

    def test_daemon_error_default(self) -> None:
        """DaemonError has a default message."""
        err = DaemonError()
        assert err.message == "Daemon error"
        assert str(err) == "Daemon error"

    def test_authentication_error_default(self) -> None:
        """AuthenticationError has a default message."""
        err = AuthenticationError()
        assert err.message == "Not authenticated"
        assert str(err) == "Not authenticated"

    def test_token_expired_default(self) -> None:
        """TokenExpiredError has a default message."""
        err = TokenExpiredError()
        assert err.message == "Token expired"
        assert str(err) == "Token expired"

    def test_rate_limit_default(self) -> None:
        """RateLimitExceeded has a default message."""
        err = RateLimitExceeded()
        assert err.message == "Rate limit exceeded"
        assert str(err) == "Rate limit exceeded"

    def test_invalid_request_default(self) -> None:
        """InvalidRequestError has a default message."""
        err = InvalidRequestError()
        assert err.message == "Invalid request"
        assert str(err) == "Invalid request"


class TestCustomMessages:
    """Tests for custom message values."""

    def test_daemon_error_custom(self) -> None:
        """DaemonError accepts a custom message."""
        err = DaemonError("custom error")
        assert err.message == "custom error"
        assert str(err) == "custom error"

    def test_authentication_error_custom(self) -> None:
        """AuthenticationError accepts a custom message."""
        err = AuthenticationError("bad token")
        assert err.message == "bad token"

    def test_token_expired_custom(self) -> None:
        """TokenExpiredError accepts a custom message."""
        err = TokenExpiredError("expired at noon")
        assert err.message == "expired at noon"

    def test_rate_limit_custom(self) -> None:
        """RateLimitExceeded accepts a custom message."""
        err = RateLimitExceeded("too many requests")
        assert err.message == "too many requests"

    def test_invalid_request_custom(self) -> None:
        """InvalidRequestError accepts a custom message."""
        err = InvalidRequestError("missing field")
        assert err.message == "missing field"


class TestRaiseAndCatch:
    """Tests for raising and catching exceptions."""

    def test_raise_daemon_error(self) -> None:
        """DaemonError can be raised and caught."""
        with pytest.raises(DaemonError, match="test"):
            raise DaemonError("test")

    def test_raise_authentication_catch_as_base(self) -> None:
        """AuthenticationError can be caught as DaemonError."""
        with pytest.raises(DaemonError):
            raise AuthenticationError("auth fail")

    def test_raise_token_expired_catch_as_base(self) -> None:
        """TokenExpiredError can be caught as DaemonError."""
        with pytest.raises(DaemonError):
            raise TokenExpiredError("expired")

    def test_raise_rate_limit_catch_as_base(self) -> None:
        """RateLimitExceeded can be caught as DaemonError."""
        with pytest.raises(DaemonError):
            raise RateLimitExceeded("limited")

    def test_raise_invalid_request_catch_as_base(self) -> None:
        """InvalidRequestError can be caught as DaemonError."""
        with pytest.raises(DaemonError):
            raise InvalidRequestError("bad req")

    def test_catch_specific_not_base(self) -> None:
        """Catching AuthenticationError does not catch DaemonError."""
        with pytest.raises(DaemonError):
            try:
                raise DaemonError("base")
            except AuthenticationError:
                pytest.fail("Should not catch as AuthenticationError")