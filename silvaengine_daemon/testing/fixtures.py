# -*- coding: utf-8 -*-
"""Test fixtures: mock logger, mock settings, and MockConfig.

These fixtures allow plugin test suites to exercise daemon substrate code
without a real gateway, database, or AWS environment.
"""
from __future__ import annotations

__author__ = "bibow"

import logging
from typing import Any, Dict

from ..config import BaseDaemonConfig


def mock_logger() -> logging.Logger:
    """Return a configured ``logging.Logger`` suitable for unit tests.

    The logger writes to stdout at DEBUG level with a simple format.
    """
    logger = logging.getLogger("silvaengine_daemon_test")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
        )
        logger.addHandler(handler)
    return logger


def mock_settings() -> Dict[str, Any]:
    """Return a minimal settings dict for unit tests.

    Includes ``db_backend`` (``"dynamodb"``), ``endpoint_id``, ``part_id``,
    and ``port``.
    """
    return {
        "db_backend": "dynamodb",
        "endpoint_id": "test-endpoint",
        "part_id": "test-part",
        "port": 8000,
        "transport": "sse",
        "auth_provider": "local",
        "jwt_secret_key": "test-secret",
        "jwt_algorithm": "HS256",
        "access_token_exp": 15,
    }


class MockConfig(BaseDaemonConfig):
    """Config subclass for testing.

    Extends ``BaseDaemonConfig`` with no additional logic. Tests can set
    ``MockConfig.DB_BACKEND``, ``MockConfig.db_session``, etc. directly
    or call ``MockConfig.initialize(mock_logger(), mock_settings())``.

    Call ``MockConfig.reset()`` in test teardown to restore defaults.
    """

    pass


__all__ = ["mock_logger", "mock_settings", "MockConfig"]