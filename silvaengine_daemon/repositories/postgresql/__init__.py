# -*- coding: utf-8 -*-
"""PostgreSQL repository helpers.

Provides ``register_all`` (generic, accepts entity specs) for PostgreSQL
repositories. Plugins register their PG repos by passing a list of
``(module_path, class_name)`` tuples.
"""
from __future__ import annotations

__author__ = "bibow"

import importlib
import logging
from typing import Dict, List, Tuple

from ..base import EntityRepository

logger = logging.getLogger(__name__)


def register_all(
    registry: Dict[str, EntityRepository],
    entity_specs: List[Tuple[str, str]],
) -> List[Tuple[str, str, Exception]]:
    """Register PostgreSQL repositories into the given registry dict.

    Args:
        registry: The registry dict to populate (``entity_type → repo``).
        entity_specs: List of ``(module_path, class_name)`` tuples. Each
            module is imported and the class is instantiated and registered
            by its ``entity_type`` property.

    Returns:
        A list of ``(module_path, class_name, error)`` for repos that could
        not be registered. Failures are logged (not silently swallowed) and
        never abort the loop. The dispatch layer uses the return value to
        decide whether to retry on the next access.
    """
    failures: List[Tuple[str, str, Exception]] = []
    for module_path, class_name in entity_specs:
        try:
            mod = importlib.import_module(module_path)
            repo_cls = getattr(mod, class_name)
            repo = repo_cls()
            registry[repo.entity_type] = repo
        except Exception as e:  # noqa: BLE001 - report every failure, keep going
            logger.warning(
                "Failed to register PostgreSQL repo %s.%s: %s: %s",
                module_path,
                class_name,
                type(e).__name__,
                e,
            )
            failures.append((module_path, class_name, e))
    return failures


__all__ = ["register_all"]