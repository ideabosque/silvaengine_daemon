# -*- coding: utf-8 -*-
"""Backend dispatch boundary for repository and loader selection.

Extracted from both engines' ``dispatch.py``. Made protocol-neutral by
replacing the hardcoded ``from ...handlers.config import Config`` import
with a configurable backend resolver callable.

``get_repo(entity_type)`` returns the active repository based on the backend
resolved by the resolver (defaulting to ``"dynamodb"``). Plugins inject their
own resolver via ``set_backend_resolver(fn)`` so ``get_repo`` uses the plugin's
``Config.DB_BACKEND``.

``get_loaders(context)`` is a forward-compatible stub (no nested resolvers
exist today). ``clear_registry()`` resets all registrations (for tests).
"""
from __future__ import annotations

__author__ = "bibow"

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .base import EntityRepository

logger = logging.getLogger(__name__)

# --- Backend resolver --------------------------------------------------------

_backend_resolver: Callable[[], str] = lambda: "dynamodb"


def set_backend_resolver(fn: Callable[[], str]) -> None:
    """Set the callable that resolves the active DB backend.

    Plugins call this at startup to inject their own ``Config.DB_BACKEND``:

        from silvaengine_daemon.repositories import set_backend_resolver
        set_backend_resolver(lambda: Config.DB_BACKEND)

    Args:
        fn: A zero-argument callable returning ``"dynamodb"`` or
            ``"postgresql"``.
    """
    global _backend_resolver
    _backend_resolver = fn


# --- Repository registry -----------------------------------------------------

_repo_registry: Dict[str, Dict[str, EntityRepository]] = {
    "dynamodb": {},
    "postgresql": {},
}


def register_repo(backend: str, entity_type: str, repo: EntityRepository) -> None:
    """Register a repository instance for a backend + entity_type."""
    if backend not in _repo_registry:
        raise ValueError(f"Unknown backend: {backend}")
    _repo_registry[backend][entity_type] = repo


def get_repo(entity_type: str, backend: Optional[str] = None) -> EntityRepository:
    """Return the active repository for the given entity type.

    Args:
        entity_type: The entity type name (e.g. ``"a2a_agent"``).
        backend: Optional backend override. If ``None``, the backend is
            resolved via the configured backend resolver callable.

    Raises:
        KeyError: If no repository is registered for the resolved
            backend + entity_type combination.
    """
    active_backend = backend if backend is not None else _backend_resolver()
    repo = _repo_registry.get(active_backend, {}).get(entity_type)
    if repo is None:
        # Lazily initialize repos on first access
        if active_backend == "dynamodb":
            _init_dynamodb_repos()
            repo = _repo_registry["dynamodb"].get(entity_type)
        elif active_backend == "postgresql":
            _init_postgresql_repos()
            repo = _repo_registry["postgresql"].get(entity_type)

    if repo is None:
        raise KeyError(
            f"No repository registered for entity '{entity_type}' "
            f"on backend '{active_backend}'"
        )
    return repo


def get_loaders(context: Dict[str, Any]) -> Any:
    """Return request-scoped loaders for the active backend.

    No nested resolvers exist today, so this is a stub.
    Returns None — implement when a nested-resolver surface is added.
    """
    return None


# --- Lazy initialization -----------------------------------------------------

_dynamodb_repos_initialized = False
_postgresql_repos_initialized = False

# Entity specs injected by plugins: list of (module_path, class_name) tuples.
_dynamodb_entity_specs: List[Tuple[str, str]] = []
_postgresql_entity_specs: List[Tuple[str, str]] = []


def register_entities(
    backend: str, entity_specs: List[Tuple[str, str]]
) -> None:
    """Register entity specs for lazy initialization.

    Plugins call this at startup to declare which repo classes to load
    for each backend:

        register_entities("dynamodb", [
            ("a2a_protocol_plugin.repositories.dynamodb.a2a_agent_repo",
             "A2AAgentRepository"),
            ...
        ])

    A single gateway process typically loads several plugins against the
    same backend (a2a_protocol_plugin, mcp_protocol_plugin, ...), each
    calling this once at startup with its own specs. This *extends* the
    shared list rather than replacing it —
    a plain assignment here would let the last plugin to initialize silently
    wipe out every earlier plugin's entities, so ``get_repo()`` would then
    raise "No repository registered" for their entity types even though
    each plugin's own ``register_entities()`` call looked like it succeeded.

    Args:
        backend: ``"dynamodb"`` or ``"postgresql"``.
        entity_specs: List of ``(module_path, class_name)`` tuples.
    """
    global _dynamodb_repos_initialized, _postgresql_repos_initialized

    if backend == "dynamodb":
        specs_list = _dynamodb_entity_specs
    elif backend == "postgresql":
        specs_list = _postgresql_entity_specs
    else:
        raise ValueError(f"Unknown backend: {backend}")

    existing = set(specs_list)
    new_specs = [spec for spec in entity_specs if spec not in existing]
    if not new_specs:
        return
    specs_list.extend(new_specs)

    # Lazy init may have already latched in using an earlier plugin's specs
    # only; unlatch so the next get_repo() call also loads these new ones.
    if backend == "dynamodb":
        _dynamodb_repos_initialized = False
    else:
        _postgresql_repos_initialized = False


def _init_dynamodb_repos() -> None:
    """Lazily register all DynamoDB repositories.

    The ``initialized`` flag is set only when every repo registered
    successfully. If any failed (e.g. a transient import error at startup),
    the flag stays False so the next get_repo() retries instead of leaving the
    registry permanently missing an entity.
    """
    global _dynamodb_repos_initialized
    if _dynamodb_repos_initialized:
        return

    failures = _register_specs(_dynamodb_entity_specs, _repo_registry["dynamodb"])
    if failures:
        logger.warning(
            "DynamoDB repo registration incomplete (%d failed); "
            "will retry on next access.",
            len(failures),
        )
    else:
        _dynamodb_repos_initialized = True


def _init_postgresql_repos() -> None:
    """Lazily register all PostgreSQL repositories.

    See ``_init_dynamodb_repos``: only lock in initialization on full success.
    """
    global _postgresql_repos_initialized
    if _postgresql_repos_initialized:
        return

    failures = _register_specs(_postgresql_entity_specs, _repo_registry["postgresql"])
    if failures:
        logger.warning(
            "PostgreSQL repo registration incomplete (%d failed); "
            "will retry on next access.",
            len(failures),
        )
    else:
        _postgresql_repos_initialized = True


def _register_specs(
    specs: List[Tuple[str, str]], registry: Dict[str, EntityRepository]
) -> List[Tuple[str, str, Exception]]:
    """Import and instantiate repos from ``(module_path, class_name)`` specs.

    Returns a list of ``(module_path, class_name, error)`` for repos that
    could not be registered. Failures are logged and never abort the loop.
    """
    import importlib

    failures: List[Tuple[str, str, Exception]] = []
    for module_path, class_name in specs:
        try:
            mod = importlib.import_module(module_path)
            repo_cls = getattr(mod, class_name)
            repo = repo_cls()
            registry[repo.entity_type] = repo
        except Exception as e:  # noqa: BLE001 - report every failure, keep going
            logger.warning(
                "Failed to register repo %s.%s: %s: %s",
                module_path,
                class_name,
                type(e).__name__,
                e,
            )
            failures.append((module_path, class_name, e))
    return failures


def clear_registry() -> None:
    """Clear resolved repository instances (useful for tests).

    Deliberately leaves ``_dynamodb_entity_specs``/``_postgresql_entity_specs``
    untouched. Plugins register their entity specs once, at import time
    (e.g. ``mcp_protocol_plugin.models.repositories.dispatch`` calling
    ``register_entities()`` at module load) — that registration never runs
    again, so a test suite that calls ``clear_registry()`` to force a fresh
    ``get_repo()`` resolution (as ``mcp_protocol_plugin``'s own
    ``test_dual_backend_guard.py`` does) would permanently lose those specs
    if this cleared them too, since nothing re-declares them afterward.
    ``register_entities()`` already deduplicates repeated ``(module_path,
    class_name)`` entries, so re-registering after a clear is harmless if a
    caller needs to do that instead.
    """
    global _dynamodb_repos_initialized, _postgresql_repos_initialized
    _repo_registry["dynamodb"].clear()
    _repo_registry["postgresql"].clear()
    _dynamodb_repos_initialized = False
    _postgresql_repos_initialized = False


__all__ = [
    "get_repo",
    "register_repo",
    "get_loaders",
    "clear_registry",
    "set_backend_resolver",
    "register_entities",
]