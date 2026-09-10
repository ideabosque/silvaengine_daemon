# -*- coding: utf-8 -*-
"""PostgreSQL SQLAlchemy base metadata and shared helpers.

Extracted from ``a2a_daemon_engine.models.postgresql.base`` (the more complete
version with the SQLAlchemy inspector pattern).

This module is only imported when ``DB_BACKEND=postgresql``.
DynamoDB-only installs never import SQLAlchemy.

Import paths fixed to use ``silvaengine_daemon.normalization``.
"""
from __future__ import annotations

__author__ = "bibow"

from typing import Any, Dict, Optional

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import scoped_session, sessionmaker
except ImportError:  # pragma: no cover - DynamoDB-only environments
    raise ImportError(
        "SQLAlchemy is required for PostgreSQL backend. "
        "Install with: pip install silvaengine-daemon[postgresql]"
    )

Base = declarative_base()


def normalize_row(row: Any) -> Optional[Dict[str, Any]]:
    """Convert a SQLAlchemy model instance to a normalized dict.

    Handles UUID, datetime, JSONB, and Decimal types for JSON serialization.

    Uses the SQLAlchemy ORM mapper to extract column attributes so the value
    is read from the correct Python attribute (mapper key), not from a
    class-level attribute that may shadow the column (e.g. the declarative
    'metadata' attribute shadows a column named 'metadata'). Output keys use
    the DB column name (``col.name``) to match GraphQL fields.
    """
    if row is None:
        return None

    from silvaengine_daemon.normalization import normalize_to_json

    if isinstance(row, dict):
        return normalize_to_json(row)

    if hasattr(row, "__table__"):
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(type(row))
        result: Dict[str, Any] = {}
        for mapper_key, col_obj in mapper.columns.items():
            key = col_obj.name
            val = getattr(row, mapper_key, None)
            result[key] = _serialize_value(val)
        return normalize_to_json(result)

    return normalize_to_json(row)


def _serialize_value(val: Any) -> Any:
    """Serialize individual SQLAlchemy column values to JSON-safe types.

    Handles ``UUID``, ``datetime``/``date``, ``Decimal``, and containers.
    Datetime objects are returned as-is (graphene's DateTime scalar calls
    ``.isoformat()`` itself; returning a string causes
    "DateTime cannot represent value").
    """
    import datetime
    from decimal import Decimal
    from uuid import UUID as UUIDType

    if val is None:
        return None
    if isinstance(val, UUIDType):
        return str(val)
    if isinstance(val, (datetime.datetime, datetime.date)):
        return val
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (list, dict)):
        return val
    return val


__all__ = ["Base", "normalize_row"]