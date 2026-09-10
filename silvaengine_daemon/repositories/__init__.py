# -*- coding: utf-8 -*-
"""Repository abstraction layer for dual-backend persistence.

Re-exports the public API: ``EntityRepository``, ``RepositoryError``,
``EntityNotFoundError``, ``DependencyExistsError``, ``get_repo``,
``register_repo``, ``get_loaders``, ``clear_registry``, ``register_entities``.
"""
from __future__ import annotations

__author__ = "bibow"

from .base import (
    EntityRepository,
    RepositoryError,
    EntityNotFoundError,
    DependencyExistsError,
)
from .dispatch import (
    get_repo,
    register_repo,
    get_loaders,
    clear_registry,
    set_backend_resolver,
    register_entities,
)

__all__ = [
    "EntityRepository",
    "RepositoryError",
    "EntityNotFoundError",
    "DependencyExistsError",
    "get_repo",
    "register_repo",
    "get_loaders",
    "clear_registry",
    "set_backend_resolver",
    "register_entities",
]
