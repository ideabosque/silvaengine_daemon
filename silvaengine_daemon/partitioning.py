# -*- coding: utf-8 -*-
"""Partition-key defaults composition.

Extracted from both engines' ``main.py``: ``_apply_partition_defaults``.

Normalizes ``endpoint_id``, ``part_id``, and ``partition_key`` into the
request params and backfills the ``context`` dict so downstream handlers
and GraphQL resolvers see a consistent tenant identity.
"""
from __future__ import annotations

__author__ = "bibow"

from typing import Any, Dict, Optional


def apply_partition_defaults(
    params: Dict[str, Any], setting: Optional[Dict[str, Any]] = None
) -> None:
    """Backfill partition defaults into *params* in-place.

    Resolution order:
    - ``endpoint_id``: ``params["endpoint_id"]`` → ``setting["endpoint_id"]``
    - ``part_id``: ``params["part_id"]`` → ``params["metadata"]["part_id"]``
      → ``setting["part_id"]``
    - ``context`` dict is created if missing
    - ``endpoint_id`` / ``part_id`` backfilled into ``context``
    - ``partition_key`` composed as ``"endpoint_id#part_id"`` or just
      ``endpoint_id`` when only the endpoint is available
    - ``partition_key`` backfilled into ``context``

    If ``params["partition_key"]`` is already set it is preserved.
    """
    setting = setting or {}

    endpoint_id: Optional[str] = params.get(
        "endpoint_id", setting.get("endpoint_id")
    )
    part_id: Optional[str] = params.get(
        "part_id",
        params.get("metadata", {}).get("part_id", setting.get("part_id")),
    )

    if params.get("context") is None:
        params["context"] = {}

    context: Dict[str, Any] = params["context"]

    if endpoint_id and "endpoint_id" not in context:
        context["endpoint_id"] = endpoint_id
    if part_id and "part_id" not in context:
        context["part_id"] = part_id

    if not params.get("partition_key"):
        if endpoint_id and part_id:
            params["partition_key"] = f"{endpoint_id}#{part_id}"
        elif endpoint_id:
            params["partition_key"] = endpoint_id

    if params.get("partition_key") and "partition_key" not in context:
        context["partition_key"] = params["partition_key"]


__all__ = ["apply_partition_defaults"]