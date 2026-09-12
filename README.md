# silvaengine_daemon

Protocol-neutral daemon substrate for SilvaEngine, designed to run behind
`silvaengine_gateway`.

This repository owns the shared Python module named `silvaengine_daemon`.
Protocol projects should import common gateway integration, partitioning,
configuration, repository, GraphQL, serialization, async, and SSE primitives
from that module instead of copying those helpers locally.

## Scope

`silvaengine_daemon` is intentionally protocol-neutral. It should not import
`a2a-sdk`, `mcp`, or Banyanos capability-engine packages at runtime.

External URLs stay in `silvaengine_gateway/routes.yaml` and
`silvaengine_gateway/module_routes/*.yaml`. This package only owns the
daemon-internal `silvaengine_daemon/config/plugin_routing.yaml` map and
per-plugin module descriptors used after the gateway has dispatched a request
to `silvaengine_daemon`.

The related project split is:

| Project | Responsibility |
| --- | --- |
| `silvaengine_gateway` | External traffic entry point that accepts requests and dispatches them to `silvaengine_daemon`. |
| `silvaengine_daemon` | Shared daemon runtime substrate that resolves YAML routing and dispatches requests to plugins. |
| `a2a_protocol_plugin` | A2A SDK, JSON-RPC, agent card, task, push, and bridge behavior. |
| `mcp_protocol_plugin` | Native MCP runtime, catalog, tool/resource/prompt handling, package lifecycle, and external MCP proxying. |

## Docs

- [SilvaEngine Daemon Development Plan](docs/SILVAENGINE_DAEMON_DEVELOPMENT_PLAN.md)
- [YAML Configuration and Plugin Routing](docs/YAML_CONFIGURATION_AND_ROUTING.md)
