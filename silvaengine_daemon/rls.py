# -*- coding: utf-8 -*-
"""Row-Level Security (RLS) helpers for the PostgreSQL backend.

Extracted from both engines' ``utils/rls.py``. Made protocol-neutral by
accepting a ``table_names`` list parameter instead of hardcoding A2A or MCP
table names.

Only imported when ``DB_BACKEND=postgresql``. DynamoDB-only installs never
import SQLAlchemy.
"""
from __future__ import annotations

__author__ = "bibow"

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def set_rls_context(session: Any, partition_key: str) -> None:
    """Set the RLS tenant context for the current database session.

    Uses connection-level ``SET`` (not ``SET LOCAL``) so the tenant context
    survives the ``commit()`` a mutation issues before subsequent reads.

    Args:
        session: A SQLAlchemy scoped session.
        partition_key: Tenant partition key to set as ``app.tenant_id``.

    Raises:
        ValueError: If *partition_key* is empty.
    """
    if not partition_key:
        raise ValueError("partition_key must be a non-empty string for RLS context.")

    from sqlalchemy import text

    session.execute(
        text("SET app.tenant_id = :tenant"),
        {"tenant": partition_key},
    )


def create_rls_policies(engine: Any, table_names: Optional[List[str]] = None) -> None:
    """Enable RLS and create tenant-isolation policies on the given tables.

    Idempotent: existing policies are dropped before re-creation.

    Args:
        engine: A SQLAlchemy engine.
        table_names: List of table names to apply RLS policies to. Each table
            must carry a ``partition_key`` column. If ``None`` or empty, no
            policies are created.
    """
    if not table_names:
        logger.warning("create_rls_policies called with no table_names — skipping.")
        return

    from sqlalchemy import text

    with engine.connect() as conn:
        for table_name in table_names:
            try:
                conn.execute(
                    text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
                )
                conn.execute(
                    text(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
                )
                conn.execute(
                    text(f"DROP POLICY IF EXISTS tenant_isolation ON {table_name}")
                )
                conn.execute(
                    text(
                        f"CREATE POLICY tenant_isolation ON {table_name} "
                        f"USING (partition_key = current_setting('app.tenant_id', true))"
                    )
                )
                logger.debug(f"RLS policy applied to {table_name}")
            except Exception as exc:
                logger.warning(f"Failed to apply RLS to {table_name}: {exc}")
        conn.commit()


__all__ = ["set_rls_context", "create_rls_policies"]