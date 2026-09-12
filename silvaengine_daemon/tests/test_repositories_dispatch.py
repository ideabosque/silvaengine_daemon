# -*- coding: utf-8 -*-
"""Tests for the shared repository dispatch registry.

A single gateway process loads several plugins against the same backend
(a2a_protocol_plugin, mcp_protocol_plugin, ...), and each calls
``register_entities(backend, specs)`` once at startup. Before this fix, that
call replaced the shared entity-spec list outright, so whichever plugin
registered last silently erased every earlier plugin's entities —
``get_repo()`` would then raise "No repository registered" for their entity
types the first time a *different* plugin's request happened to trigger lazy
initialization first. This was caught live: ``ai_agent_core_engine`` calling
into ``mcp_protocol_plugin``'s MCP config fetch failed with exactly that
error because ``a2a_protocol_plugin`` had registered after
``mcp_protocol_plugin`` and wiped out its ``mcp_function`` entity spec.
"""
from __future__ import annotations

import pytest

from silvaengine_daemon.repositories import dispatch


@pytest.fixture(autouse=True)
def _reset_registry():
    dispatch.clear_registry()
    yield
    dispatch.clear_registry()


def test_register_entities_merges_across_plugins() -> None:
    """A second plugin's registration must not erase the first plugin's specs."""
    dispatch.register_entities("postgresql", [("plugin_a.repo", "RepoA")])
    dispatch.register_entities("postgresql", [("plugin_b.repo", "RepoB")])

    assert dispatch._postgresql_entity_specs == [
        ("plugin_a.repo", "RepoA"),
        ("plugin_b.repo", "RepoB"),
    ]


def test_register_entities_is_idempotent_for_repeated_specs() -> None:
    """Re-registering the same (module_path, class_name) spec must not duplicate it."""
    dispatch.register_entities("postgresql", [("plugin_a.repo", "RepoA")])
    dispatch.register_entities("postgresql", [("plugin_a.repo", "RepoA")])

    assert dispatch._postgresql_entity_specs == [("plugin_a.repo", "RepoA")]


def test_get_repo_resolves_entities_from_every_registered_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Entities from a plugin that registers *after* lazy init already
    latched in (via an earlier plugin's get_repo() call) must still resolve —
    this is the exact sequence that caused the live failure."""
    import types

    class FakeRepo:
        def __init__(self, entity_type: str) -> None:
            self.entity_type = entity_type

    fake_module_a = types.SimpleNamespace(RepoA=lambda: FakeRepo("entity_a"))
    fake_module_b = types.SimpleNamespace(RepoB=lambda: FakeRepo("entity_b"))

    def fake_import_module(name: str):
        return {"plugin_a.repo": fake_module_a, "plugin_b.repo": fake_module_b}[name]

    monkeypatch.setattr("importlib.import_module", fake_import_module)

    dispatch.set_backend_resolver(lambda: "postgresql")

    # Plugin A registers and immediately triggers lazy init (as a plugin's
    # own Config.initialize() might do), locking in _postgresql_repos_initialized.
    dispatch.register_entities("postgresql", [("plugin_a.repo", "RepoA")])
    assert dispatch.get_repo("entity_a").entity_type == "entity_a"

    # Plugin B registers afterward — its entity must still resolve.
    dispatch.register_entities("postgresql", [("plugin_b.repo", "RepoB")])
    assert dispatch.get_repo("entity_b").entity_type == "entity_b"
    # Plugin A's entity must still resolve too.
    assert dispatch.get_repo("entity_a").entity_type == "entity_a"
