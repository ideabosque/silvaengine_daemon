# -*- coding: utf-8 -*-
"""Gateway-facing dispatch entry points for SilvaEngine daemon plugins.

``silvaengine_gateway`` owns external HTTP routes. Those routes should call
these functions first; this module then dispatches to the configured protocol
plugin. Keeping this thin layer in ``silvaengine_daemon`` preserves the intended
traffic flow:

outside traffic -> silvaengine_gateway -> silvaengine_daemon -> plugin
"""
from __future__ import annotations

__author__ = "bibow"

import importlib

from typing import Any, Callable

from .routing import get_dispatch_ref, load_dispatch_map


def _resolve_dispatch(ref_path: str) -> Callable[..., Any]:
    module_path, attr_name = ref_path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    dispatch = getattr(module, attr_name)
    if not callable(dispatch):
        raise TypeError(f"Dispatch target is not callable: {ref_path}")
    return dispatch


def dispatch_plugin(route_key: str, **params: Any) -> Any:
    """Dispatch one daemon route key to its configured plugin function."""
    ref_path = get_dispatch_ref(route_key)
    return _resolve_dispatch(ref_path)(**params)


def _make_route_dispatcher(route_key: str) -> Callable[..., Any]:
    """Build a ``dispatch_<route_key>`` wrapper around ``dispatch_plugin``.

    Gateway YAML (``silvaengine_gateway``'s ``module_routes/*.yaml``) wires
    each HTTP route to a literal ``silvaengine_daemon.gateway:dispatch_<name>``
    string, resolved via ``getattr`` at request time. Generating one such
    module-level attribute per route key defined in ``plugin_routing.yaml``
    keeps that naming contract without hand-writing (and re-syncing) a
    wrapper function for every route.
    """

    def _dispatch(**params: Any) -> Any:
        return dispatch_plugin(route_key, **params)

    _dispatch.__name__ = f"dispatch_{route_key}"
    _dispatch.__qualname__ = _dispatch.__name__
    _dispatch.__doc__ = (
        f"Gateway dispatch entry point for the {route_key!r} daemon route."
    )
    return _dispatch


_route_dispatcher_names = []
for _route_key in load_dispatch_map():
    _dispatcher_name = f"dispatch_{_route_key}"
    globals()[_dispatcher_name] = _make_route_dispatcher(_route_key)
    _route_dispatcher_names.append(_dispatcher_name)
del _route_key, _dispatcher_name

__all__ = ["dispatch_plugin", *_route_dispatcher_names]
