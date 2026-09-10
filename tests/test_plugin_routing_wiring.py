# -*- coding: utf-8 -*-
"""End-to-end wiring check for the plugin-routing structure.

``silvaengine_daemon.routing.load_dispatch_map`` only validates the *shape*
of ``config/plugin_routing.yaml`` — it never imports the plugin package a
route points at. That leaves a gap: a plugin can rename its dispatch
function, or break on import (e.g. by importing a name the daemon doesn't
actually export), and the daemon's own test suite would stay green.

This is exactly the class of bug that broke the daemon -> a2a_protocol_plugin
-> core_engine path in practice: ``a2a_protocol_plugin.main`` imported
``silvaengine_daemon.async_utils.run_async``, a name that didn't exist (only
the private ``_run_async`` was exported), so every route dispatching into
that plugin — including the one that reaches ``core_engine`` via
``CoreEngineAgentHandler`` — would fail at import time despite the routing
YAML looking perfectly valid.

These tests close that gap by actually importing each configured plugin's
dispatch target, for every route in ``plugin_routing.yaml``. Sibling plugin
checkouts are optional: a route whose plugin package isn't present on disk
is skipped rather than failed, so this suite still runs (partially) in an
environment that only has ``silvaengine_daemon`` checked out.
"""
from __future__ import annotations

__author__ = "bibow"

import importlib
import sys
from pathlib import Path
from typing import Iterable

import pytest

from silvaengine_daemon.routing import load_dispatch_map

# Sibling checkout parent directories to search for plugin packages,
# relative to this repo. Plugins live alongside silvaengine_daemon under a
# few different parent directories depending on which org owns them.
_SIBLING_PARENTS = [
    Path(__file__).resolve().parents[2],  # .../gitrepo/silvaengine
    Path(__file__).resolve().parents[3] / "banyanos",  # .../gitrepo/banyanos
]


def _register_all_sibling_plugin_checkouts() -> None:
    """Add every sibling plugin checkout to ``sys.path``, once.

    Some plugins depend on other plugins directly (e.g. capability_mcp_plugin
    imports mcp_protocol_plugin's Config), so resolving one route's package
    in isolation isn't enough — register every checkout found so cross-plugin
    imports succeed the same way they would in a real deployment where all
    plugins are installed together.
    """
    for parent in _SIBLING_PARENTS:
        if not parent.is_dir():
            continue
        for candidate in parent.iterdir():
            package_dir = candidate / candidate.name
            if (package_dir / "__init__.py").is_file():
                sys.path.insert(0, str(candidate))


_register_all_sibling_plugin_checkouts()


def _ensure_plugin_on_path(package_name: str) -> bool:
    """Return True if ``package_name`` is importable from disk."""
    try:
        importlib.import_module(package_name)
        return True
    except ImportError:
        return False


def _route_keys() -> Iterable[str]:
    return sorted(load_dispatch_map().keys())


@pytest.mark.parametrize("route_key", list(_route_keys()))
def test_route_dispatch_target_is_importable_and_callable(route_key: str) -> None:
    """Every daemon route must resolve to a real, callable plugin function."""
    dispatch_map = load_dispatch_map()
    ref_path = dispatch_map[route_key]
    module_path, attr_name = ref_path.rsplit(":", 1)
    package_name = module_path.split(".", 1)[0]

    if not _ensure_plugin_on_path(package_name):
        pytest.skip(
            f"Plugin package {package_name!r} not found on disk for route "
            f"{route_key!r} ({ref_path}); skipping (sibling checkout absent)."
        )

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        pytest.fail(
            f"Route {route_key!r} ({ref_path}) failed to import: {exc}"
        )

    assert hasattr(module, attr_name), (
        f"Route {route_key!r} points at {ref_path}, but "
        f"{module_path} has no attribute {attr_name!r}"
    )
    target = getattr(module, attr_name)
    assert callable(target), f"Dispatch target {ref_path} is not callable"
