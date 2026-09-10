# YAML Configuration and Plugin Routing

Status: planning baseline
Last updated: 2026-09-10

## Goal

`silvaengine_daemon` should use YAML for internal plugin routing and individual
plugin module descriptors. It must not duplicate `silvaengine_gateway/routes.yaml`.
Runtime settings such as environment, logging, partition context, cache flags,
and persistence backend are carried in from `silvaengine_gateway`. External
traffic hits `silvaengine_gateway` first; the gateway dispatches to
`silvaengine_daemon`, and `silvaengine_daemon` resolves internal plugin routing
and dispatches to the selected plugin.

## Files

Recommended file layout:

```text
silvaengine_daemon/
`-- config/
    |-- plugin_routing.yaml
    `-- plugins/
        |-- a2a_protocol_plugin.yaml
        |-- mcp_protocol_plugin.yaml
        `-- capability_mcp_plugin.yaml
```

`plugin_routing.yaml` owns daemon-internal plugin dispatch keys and points to
individual plugin module YAML files. It does not own external HTTP paths. Each
`plugins/*.yaml` file describes how to load one plugin module and which route
keys that plugin contributes. Shared runtime settings come from the gateway
setting dictionary produced by
`silvaengine_gateway/settings.yaml`.

## Gateway-Carried Settings

Do not duplicate gateway-owned values in daemon YAML. The daemon should consume
these values from the setting dictionary passed by `silvaengine_gateway`:

| Setting | Source of Truth |
| --- | --- |
| Environment and logging | Gateway process environment and `silvaengine_gateway/settings.yaml`. |
| Partition context | Gateway route path, request headers such as `Part-Id`, and normalized request context. |
| Cache flags and TTLs | Gateway setting dictionary, with plugin-specific cache knobs in plugin module YAML only when not environment-specific. |
| Persistence backend and DSN/env names | Gateway setting dictionary. Secrets and connection strings remain environment-backed. |
| External HTTP paths | `silvaengine_gateway/routes.yaml` and its `module_routes/*.yaml` fragments. |
| Module identity | `plugin_routing.yaml` and each plugin module YAML descriptor, not a daemon settings file. |

Required behavior:

- Treat the gateway setting dictionary as the source of runtime values.
- Validate required setting keys before dispatching to plugins.
- Keep secrets out of daemon YAML.
- Do not redefine gateway settings or external HTTP paths in daemon routing YAML.
- Fail startup or route activation when required gateway-carried settings are
  missing for an enabled route.

## Internal Plugin Routing Schema

`plugin_routing.yaml` is the daemon-internal routing file. It should not
duplicate `silvaengine_gateway/routes.yaml`, `silvaengine_gateway/module_routes`,
or each plugin's full route metadata. It maps daemon dispatch keys to plugin
route keys and points to the individual plugin module YAML files that must be
loaded.

```yaml
version: 1
router:
  default_partition_policy: request_context
  plugin_module_files:
    - plugins/a2a_protocol_plugin.yaml
    - plugins/mcp_protocol_plugin.yaml
    - plugins/capability_mcp_plugin.yaml
  routes:
    - name: a2a_jsonrpc
      plugin: a2a_protocol_plugin
      plugin_route: jsonrpc
    - name: a2a_agent_card
      plugin: a2a_protocol_plugin
      plugin_route: agent_card
    - name: mcp_jsonrpc
      plugin: mcp_protocol_plugin
      plugin_route: jsonrpc
    - name: mcp_graphql
      plugin: mcp_protocol_plugin
      plugin_route: graphql
    - name: capability_mcp_graphql
      plugin: capability_mcp_plugin
      plugin_route: graphql
```

Required behavior:

- `plugin_routing.yaml` must load every file listed in `plugin_module_files`.
- Each route must define `name`, `plugin`, and `plugin_route`.
- Route names must be globally unique.
- `plugin` must match a loaded plugin module descriptor.
- `plugin_route` must match a route key declared inside that plugin's YAML.
- Disabled plugin modules must not register routes, even when referenced.
- Route loading should produce a deterministic daemon-internal dispatch map.
- `silvaengine_gateway` owns external paths and calls `silvaengine_daemon` with a
  daemon route name or equivalent request context.

## Plugin Module Schema

Each individual plugin module YAML file defines the package to import and the
dispatch functions exposed by that plugin. This file is the source of truth for
loading the plugin module.

Example `silvaengine_daemon/config/plugins/a2a_protocol_plugin.yaml`:

```yaml
version: 1
plugin:
  name: a2a_protocol_plugin
  package: a2a_protocol_plugin
  enabled: true
  protocol: a2a
  settings:
    stream_timeout_seconds: 300
    default_agent_type: a2a_proxy
  routes:
    jsonrpc:
      dispatch: dispatch_a2a
      partition_policy: endpoint_part
      methods:
        - POST
    agent_card:
      dispatch: dispatch_agent_card
      partition_policy: endpoint_only
      methods:
        - GET
```

Example `silvaengine_daemon/config/plugins/mcp_protocol_plugin.yaml`:

```yaml
version: 1
plugin:
  name: mcp_protocol_plugin
  package: mcp_protocol_plugin
  enabled: true
  protocol: mcp
  settings:
    package_cache_ttl_seconds: 300
    external_sync_enabled: true
  routes:
    jsonrpc:
      dispatch: dispatch_mcp
      partition_policy: endpoint_part
      methods:
        - POST
    graphql:
      dispatch: dispatch_graphql
      partition_policy: request_context
      methods:
        - POST
```

Example `silvaengine_daemon/config/plugins/capability_mcp_plugin.yaml`:

```yaml
version: 1
plugin:
  name: capability_mcp_plugin
  package: capability_mcp_plugin
  enabled: true
  protocol: capability_mcp
  settings:
    legacy_id_aliases_enabled: true
  routes:
    graphql:
      dispatch: dispatch_graphql
      partition_policy: request_context
      methods:
        - POST
```

Required behavior:

- Each plugin module file must define `plugin.name`, `plugin.package`,
  `plugin.enabled`, `plugin.protocol`, and `plugin.routes`.
- `plugin.package` is the Python package imported to load the plugin module.
- Each route key under `plugin.routes` is addressable by `plugin_routing.yaml` through
  `plugin_route`.
- Each plugin route must define `dispatch`, `partition_policy`, and `methods`.
  The methods are metadata for validation; `silvaengine_gateway/routes.yaml`
  remains the HTTP method enforcement point.
- Dispatch functions are resolved from `plugin.package` at startup.
- Plugin-specific settings live in the plugin module YAML, not in
  `settings.yaml` or `plugin_routing.yaml`.
- Invalid plugin module files should fail startup before route registration.

## Resolved Manifest

After loading `plugin_routing.yaml`, the referenced plugin module YAML files, and the
gateway-carried setting dictionary, `silvaengine_daemon.routing` should build a
normalized daemon-internal dispatch map:

```yaml
routes:
  - name: a2a_jsonrpc
    methods:
      - POST
    enabled: true
    protocol: a2a
    plugin: a2a_protocol_plugin
    package: a2a_protocol_plugin
    dispatch: dispatch_a2a
    partition_policy: endpoint_part
  - name: mcp_graphql
    methods:
      - POST
    enabled: true
    protocol: mcp
    plugin: mcp_protocol_plugin
    package: mcp_protocol_plugin
    dispatch: dispatch_graphql
    partition_policy: request_context
```

The resolved dispatch map is generated data. It should be stable and testable,
but it should not be hand-edited. `silvaengine_gateway` should use its existing
route manifest to route outside traffic to `silvaengine_daemon`.
`silvaengine_daemon` then uses its internal dispatch map to invoke the
referenced plugin dispatch functions.

## Partition Policies

Initial policy names:

| Policy | Behavior |
| --- | --- |
| `endpoint_only` | Resolve partition context from `endpoint_id` only. |
| `endpoint_part` | Compose `partition_key` from `endpoint_id` and `part_id` when one is not supplied. |
| `request_context` | Trust normalized gateway request context and backfill missing defaults. |
| `explicit` | Require caller-supplied `partition_key`; fail if absent. |

## Implementation Notes

- Add `silvaengine_daemon.config` for validating gateway-carried settings and
  exposing typed daemon/plugin configuration views.
- Add `silvaengine_daemon.routing` for internal plugin routing YAML loading,
  plugin module YAML loading, dispatch resolution, partition policy validation,
  and dispatch map generation.
- Keep HTTP server concerns and external ingress in `silvaengine_gateway`; keep
  plugin loading, dispatch metadata, and partition policy resolution in
  `silvaengine_daemon`.
- Treat YAML structures as data contracts. Keep protocol-specific route payload
  behavior in the protocol plugins.
- Add tests for gateway-carried setting validation, invalid YAML, missing plugin
  module files, duplicate route names, disabled plugin filtering, missing
  dispatch functions, unresolved `plugin_route` values, and partition policy
  validation.
