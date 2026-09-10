# -*- coding: utf-8 -*-
"""Protocol-neutral daemon substrate for SilvaEngine.

This package provides shared daemon functionality extracted from
``a2a_daemon_engine`` and ``mcp_daemon_engine``: exception hierarchies,
serialization helpers, normalization utilities, partition-key composition,
SSE client management, repository dispatch, configuration base classes,
GraphQL execution helpers, and Row-Level Security support.

Protocol-specific code (A2A SDK, MCP SDK) is intentionally excluded —
plugins import only the substrate they need from here.
"""
from __future__ import annotations

__author__ = "bibow"

from . import errors
from . import gateway
from . import normalization
from . import partitioning
from . import routing
from . import sse
from . import repositories

__all__ = [
    "errors",
    "gateway",
    "normalization",
    "partitioning",
    "routing",
    "sse",
    "repositories",
]
