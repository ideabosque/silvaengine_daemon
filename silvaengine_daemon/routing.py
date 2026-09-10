# -*- coding: utf-8 -*-
"""Internal plugin routing for ``silvaengine_daemon``.

Gateway YAML owns external HTTP paths. This module owns the daemon-internal map
from route keys to plugin dispatch functions, loaded from package YAML files.
"""
from __future__ import annotations

__author__ = "bibow"

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping

import yaml


class RoutingError(ValueError):
    """Raised when daemon plugin routing YAML is invalid."""


def _read_yaml(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise RoutingError(f"YAML root must be a mapping: {path}")
    return data


def _default_config_path() -> Path:
    return Path(__file__).resolve().parent / "config" / "plugin_routing.yaml"


@lru_cache(maxsize=8)
def load_dispatch_map(config_path: str | None = None) -> Dict[str, str]:
    """Load daemon route key -> plugin dispatch reference map from YAML."""
    routing_path = Path(config_path).resolve() if config_path else _default_config_path()
    routing_data = _read_yaml(routing_path)
    router = routing_data.get("router")
    if not isinstance(router, dict):
        raise RoutingError("plugin_routing.yaml must define router")

    module_files = router.get("plugin_module_files")
    if not isinstance(module_files, list) or not module_files:
        raise RoutingError("router.plugin_module_files must be a non-empty list")

    plugins: Dict[str, Dict[str, Any]] = {}
    for module_file in module_files:
        module_path = (routing_path.parent / str(module_file)).resolve()
        plugin_data = _read_yaml(module_path).get("plugin")
        if not isinstance(plugin_data, dict):
            raise RoutingError(f"Plugin module file must define plugin: {module_path}")
        plugin_name = plugin_data.get("name")
        if not plugin_name:
            raise RoutingError(
                f"Plugin module file is missing plugin.name: {module_path}"
            )
        if plugin_name in plugins:
            raise RoutingError(f"Duplicate plugin module name: {plugin_name}")
        plugins[str(plugin_name)] = plugin_data

    routes = router.get("routes")
    if not isinstance(routes, list) or not routes:
        raise RoutingError("router.routes must be a non-empty list")

    dispatch_map: Dict[str, str] = {}
    for route in routes:
        if not isinstance(route, Mapping):
            raise RoutingError("Each router.routes entry must be a mapping")
        route_name = str(route.get("name") or "")
        plugin_name = str(route.get("plugin") or "")
        plugin_route = str(route.get("plugin_route") or "")
        if not route_name or not plugin_name or not plugin_route:
            raise RoutingError("Each route requires name, plugin, and plugin_route")
        if route_name in dispatch_map:
            raise RoutingError(f"Duplicate daemon route name: {route_name}")

        plugin = plugins.get(plugin_name)
        if not plugin:
            raise RoutingError(
                f"Route {route_name} references unknown plugin {plugin_name}"
            )
        if plugin.get("enabled") is False:
            continue

        plugin_routes = plugin.get("routes")
        if not isinstance(plugin_routes, dict) or plugin_route not in plugin_routes:
            raise RoutingError(
                f"Route {route_name} references unknown plugin route "
                f"{plugin_name}.{plugin_route}"
            )
        route_config = plugin_routes[plugin_route]
        if not isinstance(route_config, dict):
            raise RoutingError(
                f"Plugin route must be a mapping: {plugin_name}.{plugin_route}"
            )

        package = plugin.get("package")
        dispatch = route_config.get("dispatch")
        if not package or not dispatch:
            raise RoutingError(
                f"Plugin route requires plugin.package and dispatch: "
                f"{plugin_name}.{plugin_route}"
            )
        module = route_config.get("module", "main")
        dispatch_map[route_name] = f"{package}.{module}:{dispatch}"

    return dispatch_map


def get_dispatch_ref(route_key: str, config_path: str | None = None) -> str:
    """Return the plugin dispatch reference for one daemon route key."""
    try:
        return load_dispatch_map(config_path)[route_key]
    except KeyError as exc:
        raise RoutingError(f"Unknown silvaengine_daemon route key: {route_key}") from exc


__all__ = ["RoutingError", "load_dispatch_map", "get_dispatch_ref"]
