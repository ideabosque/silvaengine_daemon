# -*- coding: utf-8 -*-
"""JSON serialization helpers for daemon responses.

Extracted from both engines' ``main.py``: ``_json_default`` and ``dumps``.

The SDK ``model_dump(mode="json")`` generally yields JSON-native types, but
some fields (e.g. pendulum ``DateTime`` from task timestamps / history)
survive as datetime objects, and ``json.dumps`` then raises
``Object of type DateTime is not JSON serializable``. Coerce datetimes to
ISO 8601 strings so the JSON-RPC response always serializes.
"""
from __future__ import annotations

__author__ = "bibow"

import json
from datetime import datetime
from typing import Any


def _json_default(obj: Any) -> Any:
    """JSON default handler for non-stdlib types that daemons can emit.

    Handles ``datetime``, pendulum-like objects (via ``isoformat``),
    Pydantic v2 models (``model_dump``), Pydantic v1 models (``dict``),
    and falls back to ``str()``.
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    # pendulum.DateTime subclasses datetime, so the above covers it; keep a
    # generic fallback for any other object exposing isoformat().
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "dict"):
        return obj.dict()
    return str(obj)


def dumps(result: Any) -> str:
    """Serialize *result* to a JSON string with the datetime-aware default handler."""
    return json.dumps(result, default=_json_default)


__all__ = ["_json_default", "dumps"]