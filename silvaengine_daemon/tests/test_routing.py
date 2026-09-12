# -*- coding: utf-8 -*-
"""Tests for daemon-internal YAML plugin routing."""
from __future__ import annotations

from pathlib import Path

import pytest

from silvaengine_daemon.routing import RoutingError, get_dispatch_ref, load_dispatch_map


def test_load_default_dispatch_map() -> None:
    load_dispatch_map.cache_clear()
    dispatch_map = load_dispatch_map()
    assert dispatch_map["a2a_jsonrpc"] == "a2a_protocol_plugin.main:dispatch_a2a"
    assert dispatch_map["mcp_graphql"] == "mcp_protocol_plugin.main:dispatch_graphql"
    assert "capability_mcp_graphql" not in dispatch_map


def test_get_dispatch_ref_rejects_unknown_route_key() -> None:
    load_dispatch_map.cache_clear()
    with pytest.raises(RoutingError, match="Unknown silvaengine_daemon route key"):
        get_dispatch_ref("missing")


def test_load_dispatch_map_rejects_unresolved_plugin_route(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "demo.yaml").write_text(
        """
version: 1
plugin:
  name: demo
  package: demo_plugin
  enabled: true
  protocol: demo
  routes:
    known:
      dispatch: dispatch_known
      partition_policy: request_context
      methods: [POST]
""".strip(),
        encoding="utf-8",
    )
    routing_file = tmp_path / "plugin_routing.yaml"
    routing_file.write_text(
        """
version: 1
router:
  plugin_module_files:
    - plugins/demo.yaml
  routes:
    - name: demo_missing
      plugin: demo
      plugin_route: missing
""".strip(),
        encoding="utf-8",
    )

    load_dispatch_map.cache_clear()
    with pytest.raises(RoutingError, match="unknown plugin route"):
        load_dispatch_map(str(routing_file))
