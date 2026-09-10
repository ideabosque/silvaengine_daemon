# -*- coding: utf-8 -*-
"""Model-to-JSON normalization utility.

Extracted from both engines' ``utils/normalization.py`` — identical in both.

Uses ``silvaengine_utility.serializer.Serializer`` to convert PynamoDB model
instances, plain objects, and dicts into JSON-serializable data.
"""
from __future__ import annotations

__author__ = "bibow"

from typing import Any

from silvaengine_utility.serializer import Serializer


def normalize_to_json(item: Any) -> Any:
    """Convert model objects or plain objects into JSON-serializable data.

    Handles:
    - ``dict`` → ``Serializer.json_normalize``
    - PynamoDB models (``attribute_values``) → ``Serializer.json_normalize``
    - Plain objects (``__dict__`` minus private attrs) → ``Serializer.json_normalize``
    - Everything else → returned as-is
    """
    if isinstance(item, dict):
        return Serializer.json_normalize(item)
    if hasattr(item, "attribute_values"):
        return Serializer.json_normalize(item.attribute_values)
    if hasattr(item, "__dict__"):
        return Serializer.json_normalize(
            {k: v for k, v in vars(item).items() if not k.startswith("_")}
        )
    return item


__all__ = ["normalize_to_json"]