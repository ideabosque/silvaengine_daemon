# -*- coding: utf-8 -*-
"""Shared helpers for DynamoDB repositories.

Extracted identically from both engines'
``models/repositories/dynamodb/_base.py`` (23 lines, identical).

Import path updated to use ``silvaengine_daemon.normalization``.
"""
from __future__ import annotations

__author__ = "bibow"

from typing import Any, Dict

from ...normalization import normalize_to_json


def _normalize(model: Any) -> Dict[str, Any] | None:
    """Convert a PynamoDB model instance to a normalized dict.

    Handles ``None``, PynamoDB models (``attribute_values``), plain dicts,
    and any other object via ``normalize_to_json``.
    """
    if model is None:
        return None
    if hasattr(model, "attribute_values"):
        return normalize_to_json(model.attribute_values)
    if isinstance(model, dict):
        return normalize_to_json(model)
    return normalize_to_json(model)


__all__ = ["_normalize"]