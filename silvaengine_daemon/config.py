# -*- coding: utf-8 -*-
"""Protocol-neutral base configuration class for daemon plugins.

``BaseDaemonConfig`` provides the shared configuration substrate that plugin
``Config`` classes extend. It stores a logger and setting dict, parses the
``DB_BACKEND`` selection (``dynamodb`` or ``postgresql``), and delegates RLS
context setup to ``silvaengine_daemon.rls`` when PostgreSQL is active.

Plugin Config classes add their own entity-specific cache metadata, AWS
service initialization, and protocol-specific server setup on top of this base.
"""
from __future__ import annotations

__author__ = "bibow"

import logging
from typing import Any, Dict, Optional


class BaseDaemonConfig:
    """Protocol-neutral base configuration class for daemon plugins.

    Subclasses extend this with entity-specific cache config, AWS services,
    and protocol server initialization. The base provides:

    - ``initialize(logger, setting)`` — stores logger/setting, parses DB_BACKEND
    - ``get_logger()`` / ``get_setting()`` / ``reset()`` — accessors
    - ``DB_BACKEND`` property — ``"dynamodb"`` or ``"postgresql"``
    - ``_set_rls_context(partition_key)`` — delegates to ``rls.set_rls_context``
    - ``db_session`` — ``None`` for DynamoDB; scoped SQLAlchemy session for PG
    """

    # Backend selection: "dynamodb" (default) or "postgresql"
    DB_BACKEND: str = "dynamodb"
    db_session: Any = None

    # Application settings (populated by initialize)
    setting: Dict[str, Any] = {}
    logger: Optional[logging.Logger] = None

    @classmethod
    def initialize(cls, logger: logging.Logger, setting: Dict[str, Any]) -> None:
        """Initialize the base configuration.

        Stores the logger and setting dict, then parses ``DB_BACKEND`` from
        ``setting["db_backend"]`` (defaulting to ``"dynamodb"``).

        Subclasses should call ``super().initialize(logger, setting)`` first,
        then add their own initialization (AWS services, protocol servers,
        cache config, etc.).

        Args:
            logger: Logger instance for the daemon.
            setting: Configuration dictionary from the gateway.
        """
        cls.logger = logger
        cls.setting = setting
        cls.DB_BACKEND = str(setting.get("db_backend", "dynamodb")).lower()

    @classmethod
    def get_logger(cls) -> logging.Logger:
        """Return the initialized application logger."""
        return cls.logger  # type: ignore[return-value]

    @classmethod
    def get_setting(cls) -> Dict[str, Any]:
        """Return the initialized application settings."""
        return cls.setting

    @classmethod
    def reset(cls) -> None:
        """Reset all configuration to defaults (useful for tests)."""
        cls.DB_BACKEND = "dynamodb"
        cls.db_session = None
        cls.setting = {}
        cls.logger = None

    @classmethod
    def _set_rls_context(cls, partition_key: str) -> None:
        """Set the RLS tenant context for the current PostgreSQL session.

        No-op when ``DB_BACKEND`` is not ``"postgresql"`` or when no
        ``db_session`` is initialized.
        """
        if cls.DB_BACKEND == "postgresql" and cls.db_session and partition_key:
            from .rls import set_rls_context

            set_rls_context(cls.db_session, partition_key)


__all__ = ["BaseDaemonConfig"]