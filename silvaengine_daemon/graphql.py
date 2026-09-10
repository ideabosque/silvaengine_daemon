# -*- coding: utf-8 -*-
"""Base GraphQL engine class for daemon plugins.

``BaseDaemonGraphql`` extends ``silvaengine_utility.Graphql`` and standardizes
the partition-defaults, async-execution, and RLS-aware GraphQL execution
patterns shared by both ``a2a_daemon_engine.main.A2ADaemonEngine`` and
``mcp_daemon_engine.main.AIMCPDaemonEngine``.

Plugin engine classes extend this base and provide their own
``build_graphql_schema()`` static method.
"""
from __future__ import annotations

__author__ = "bibow"

import logging
from typing import Any, Dict

from silvaengine_utility import Graphql

from .async_utils import _run_async
from .partitioning import apply_partition_defaults


class BaseDaemonGraphql(Graphql):
    """Base GraphQL engine class with partition defaults and RLS support.

    Subclasses provide:
    - ``build_graphql_schema()`` — returns a ``graphene.Schema``
    - Protocol-specific methods (``a2a()``, ``mcp()``, etc.)

    The base handles:
    - ``__init__(logger, **setting)`` calling ``Graphql.__init__``
    - ``apply_partition_defaults(params)`` delegating to partitioning module
    - ``run_async(coro)`` delegating to async_utils
    - ``execute_with_rls(params, schema)`` — sets RLS context, executes
      GraphQL, and tears down the session
    """

    def __init__(self, logger: logging.Logger, **setting: Dict[str, Any]) -> None:
        """Initialize the GraphQL engine.

        Args:
            logger: Logger instance.
            **setting: Configuration keyword arguments forwarded to
                ``Graphql.__init__``.
        """
        Graphql.__init__(self, logger, **setting)
        self.logger = logger
        self.setting = setting

    def apply_partition_defaults(self, params: Dict[str, Any]) -> None:
        """Backfill partition defaults into *params* in-place.

        Delegates to ``silvaengine_daemon.partitioning.apply_partition_defaults``
        using ``self.setting`` as the fallback setting.
        """
        apply_partition_defaults(params, self.setting)

    def run_async(self, coro: Any) -> Any:
        """Run an async coroutine from a sync context.

        Delegates to ``silvaengine_daemon.async_utils._run_async``.
        """
        return _run_async(coro)

    def execute_with_rls(self, params: Dict[str, Any], schema: Any) -> Any:
        """Execute a GraphQL query with RLS context set and session teardown.

        Pattern extracted from both engines' ``a2a_core_graphql`` /
        ``mcp_core_graphql`` methods:

        1. Apply partition defaults to *params*
        2. Resolve ``partition_key`` from params or context
        3. Set RLS context (if PostgreSQL backend is active)
        4. Execute the GraphQL schema
        5. Tear down the scoped session (if PostgreSQL)

        Args:
            params: Request parameters dict.
            schema: A ``graphene.Schema`` instance to execute.

        Returns:
            The GraphQL execution result.
        """
        from .config import BaseDaemonConfig

        self.apply_partition_defaults(params)
        partition_key = params.get("partition_key") or params.get(
            "context", {}
        ).get("partition_key")

        if partition_key and BaseDaemonConfig.DB_BACKEND == "postgresql":
            BaseDaemonConfig._set_rls_context(partition_key)
        try:
            return self.execute(schema, **params)
        finally:
            if BaseDaemonConfig.DB_BACKEND == "postgresql" and BaseDaemonConfig.db_session:
                BaseDaemonConfig.db_session.remove()


__all__ = ["BaseDaemonGraphql"]