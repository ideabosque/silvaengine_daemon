# -*- coding: utf-8 -*-
"""Tests for gateway-facing daemon dispatch wrappers."""
from __future__ import annotations

import types

import pytest

from silvaengine_daemon import gateway


def test_dispatch_plugin_resolves_configured_target(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_import_module(module_path: str):
        assert module_path == "a2a_protocol_plugin.main"

        def dispatch_graphql(**params):
            calls.append(params)
            return {"ok": True, "params": params}

        return types.SimpleNamespace(dispatch_graphql=dispatch_graphql)

    monkeypatch.setattr(gateway.importlib, "import_module", fake_import_module)

    result = gateway.dispatch_plugin("a2a_graphql", endpoint_id="ep1")

    assert result == {"ok": True, "params": {"endpoint_id": "ep1"}}
    assert calls == [{"endpoint_id": "ep1"}]


def test_dispatch_plugin_rejects_unknown_route_key() -> None:
    with pytest.raises(ValueError, match="Unknown silvaengine_daemon route key"):
        gateway.dispatch_plugin("missing")
