# SilvaEngine Daemon Development Plan

Status: planning baseline
Last updated: 2026-09-10

> **2026-09-12 update**: the `capability_mcp_plugin` plugin described below was
> retired and removed from `silvaengine_daemon`/`silvaengine_gateway` routing.
> Its GraphQL compatibility surface was absorbed directly into
> Banyanos's `capability_engine`, which now talks to `mcp_protocol_plugin`
> over HTTP through the gateway (see
> `capability_engine/docs/CAPABILITY_MCP_PLUGIN_MERGE_PLAN.md`) instead of
> being a separately-routed daemon plugin. The sections below referencing
> `capability_mcp_plugin` are historical context for that now-superseded plan.

## Goal

`silvaengine_daemon` provides the protocol-neutral daemon layer behind
`silvaengine_gateway`. Outside traffic should hit `silvaengine_gateway` first;
the gateway dispatches to `silvaengine_daemon`, and `silvaengine_daemon`
dispatches to the selected plugin. It should keep the generic daemon functions
duplicated across `a2a_daemon_engine` and `mcp_daemon_engine`, while protocol and
capability surfaces move into separate plugins:

- A2A protocol code -> `a2a_protocol_plugin`
- MCP protocol code -> `mcp_protocol_plugin`
- Capability-facing MCP compatibility code -> `capability_mcp_plugin`

The core module must not import `a2a-sdk`, `mcp`, or Banyanos capability-engine
packages at runtime.

`silvaengine_gateway` remains the HTTP/gateway hosting layer and the only
external traffic entry point. `silvaengine_daemon` should provide the module
contract, plugin routing YAML, internal dispatch map, context normalization,
gateway-carried setting validation, and runtime helpers that the gateway calls.
Plugin dispatch stays inside `silvaengine_daemon`, not inside
`silvaengine_gateway`.

## Current Inputs

The split is based on these source projects:

- `C:\Users\bibo7\gitrepo\silvaengine\silvaengine_gateway`
- `C:\Users\bibo7\gitrepo\silvaengine\a2a_daemon_engine`
- `C:\Users\bibo7\gitrepo\silvaengine\mcp_daemon_engine`

The old packages are gateway-dispatched Python modules. Both expose `deploy()`,
`Graphql` subclasses, module-level dispatch functions, partition defaults,
DynamoDB/PostgreSQL repository dispatch, config singletons, RLS setup, GraphQL
CRUD types/mutations/queries, and SSE helpers.

## Repository and Module Naming

`silvaengine_daemon` replaces the earlier planning repository and is also the
importable Python module name.

Expected package shape:

```text
silvaengine_daemon/
|-- silvaengine_daemon/
|   |-- __init__.py
|   |-- gateway.py
|   |-- config.py
|   |-- routing.py
|   |-- graphql.py
|   |-- serialization.py
|   |-- async_utils.py
|   |-- errors.py
|   |-- partitioning.py
|   |-- sse.py
|   |-- config/
|   |   |-- plugin_routing.yaml
|   |   `-- plugins/
|   |       |-- a2a_protocol_plugin.yaml
|   |       |-- mcp_protocol_plugin.yaml
|   |       `-- capability_mcp_plugin.yaml
|   |-- repositories/
|   |   |-- base.py
|   |   |-- dispatch.py
|   |   |-- dynamodb.py
|   |   `-- postgresql.py
|   `-- testing/
|       |-- fixtures.py
|       `-- gateway.py
|-- docs/
|   `-- SILVAENGINE_DAEMON_DEVELOPMENT_PLAN.md
|-- pyproject.toml
`-- README.md
```

## Target Ownership

`silvaengine_daemon` should own only reusable daemon substrate that plugs into
`silvaengine_gateway`:

| Area | Keep in `silvaengine_daemon` |
| --- | --- |
| Gateway integration contract | Shared `deploy()` helpers, function manifest builder, gateway-to-daemon dispatch entry point, and request context normalization for `silvaengine_gateway`. |
| Partitioning | `endpoint_id`, `part_id`, `partition_key` composition and context injection. |
| Configuration | Base config adapter for gateway-carried settings, logger/settings access, cache TTL/name conventions, persistence backend parsing. |
| Plugin routing | Internal `plugin_routing.yaml`, per-plugin module YAML descriptors, protocol dispatch map, route validation, and route metadata loading. |
| Persistence abstractions | Repository base interfaces, backend registry, DynamoDB/PostgreSQL dispatch pattern, RLS helpers. |
| GraphQL foundation | Common GraphQL execution wrapper, pagination/list result helpers, JSON scalar conventions, mutation cache invalidation hooks. |
| Runtime utilities | JSON normalization, datetime serialization, async-from-sync runner, structured error base classes. |
| SSE primitives | Generic partition/user-scoped SSE manager if protocol-agnostic after extracting event names. |

Protocol-specific behavior must remain outside this package:

- A2A JSON-RPC methods, A2A SDK request/response types, agent cards, task state
  mapping, A2A task store, A2A push notification store, and A2A bridge handlers.
- MCP server SDK objects, MCP JSON-RPC method table, tool/resource/prompt
  serialization, dynamic MCP module invocation, and external MCP proxying.
- Capability MCP provider/server/tool/invocation compatibility schema and
  Banyanos-shaped GraphQL names.

## Related Project Updates

### `a2a_protocol_plugin`

- Depend on `silvaengine_daemon` for shared gateway dispatch, partition defaults,
  context normalization, base config, repository contracts, GraphQL execution,
  serialization, async runner, and generic SSE primitives.
- Keep A2A SDK imports, JSON-RPC handlers, agent cards, task/push stores, task
  state mapping, and backend bridges inside the plugin.
- Port docs from `a2a_daemon_engine` only after import paths are renamed from
  `a2a_daemon_engine` to `a2a_protocol_plugin`.

### `mcp_protocol_plugin`

- Depend on `silvaengine_daemon` for shared daemon runtime concerns.
- Keep native MCP SDK/runtime handling, tool/resource/prompt APIs, package
  upload/install/refresh flows, external MCP proxying, and MCP catalog entities
  inside the plugin.
- Extract capability compatibility GraphQL files instead of carrying them as
  part of the native MCP schema long term.

### `capability_mcp_plugin`

- Existing project:
  `C:\Users\bibo7\gitrepo\banyanos\capability_mcp_plugin`.
- Populate this project from the current capability-facing files in
  `mcp_daemon_engine`: `types/capability_mcp.py`,
  `queries/capability_mcp.py`, `mutations/capability_mcp.py`, and
  `handlers/capability_mcp_invoke.py`.
- Depend on `silvaengine_daemon` for shared daemon runtime behavior and on a stable
  service API from `mcp_protocol_plugin` for provider registration, catalog
  lookup, and tool invocation.
- Avoid GraphQL-to-GraphQL loops inside the same process; use direct service
  functions for in-process integration and GraphQL only at the gateway boundary.

## Migration Phases

### Phase 1: Extract Shared Utilities

- Copy the common exception, normalization, datetime serialization, and
  `_run_async` patterns from the old packages.
- Implement `apply_partition_defaults(params, setting)` once and replace the
  old per-package copies after plugin migration.
- Add unit tests for partition composition:
  `endpoint_id + part_id -> endpoint_id#part_id`, context backfill, and
  pass-through when `partition_key` already exists.

### Phase 2: Extract Config and Repository Contracts

- Create `BaseDaemonConfig` around the setting dictionary carried from
  `silvaengine_gateway`, with logger/settings lifecycle, DB backend parsing,
  cache configuration, and PostgreSQL RLS session hooks.
- Add strict YAML schemas for the internal plugin routing file and individual plugin
  module descriptors. Do not duplicate gateway-owned runtime settings in daemon
  YAML, and do not duplicate `silvaengine_gateway/routes.yaml`.
- Move repository interfaces and backend registry behavior into
  `silvaengine_daemon.repositories`.
- Keep entity-specific repository implementations in protocol plugins until a
  dedicated shared model package is justified.
- Add contract tests that plugin repositories can register and resolve by
  backend/entity name.

### Phase 3: Extract Gateway/GraphQL Runtime

- Provide a small base class around `silvaengine_utility.Graphql` to standardize
  request setup, RLS setup/teardown, and cache invalidation after config
  mutations.
- Add a dispatch-map builder so plugins declare function metadata without copying
  the same boilerplate.
- Load plugin routing from internal `plugin_routing.yaml`, then load each
  referenced plugin module YAML file and validate that each daemon route key maps
  to an installed plugin, plugin route key, dispatch function, protocol,
  partition policy, and required gateway-carried settings.
- Keep external HTTP paths in `silvaengine_gateway/routes.yaml`; the gateway
  should route to `silvaengine_daemon`, and `silvaengine_daemon` should resolve
  the plugin dispatch function.
- Keep actual GraphQL fields in plugins.

### Phase 4: Extract Generic SSE

- Generalize the `sse_manager.py` behavior from both old projects into
  partition/user-scoped primitives.
- Protocol plugins should pass event payloads and event type names; the core
  manager should only manage connections, queues, fan-out, stats, and cleanup.
- Add tests for per-user send, per-partition broadcast, cleanup, and queue
  overflow behavior.

### Phase 5: Cut Plugins Over

- Update `a2a_protocol_plugin`, `mcp_protocol_plugin`, and
  `capability_mcp_plugin` to depend on `silvaengine_daemon`.
- Remove duplicated shared helpers from plugin packages once tests pass.
- Verify old gateway dispatch routes still work through compatibility shims
  before retiring `a2a_daemon_engine` and `mcp_daemon_engine`.

## Acceptance Criteria

- `silvaengine_daemon` installs as a distribution and exposes the
  `silvaengine_daemon` import package.
- `silvaengine_daemon` installs without `a2a-sdk`, `mcp`, or Banyanos dependencies.
- Shared partition/config/repository/SSE tests pass in isolation.
- `plugin_routing.yaml` and plugin module YAML files validate against the
  documented schemas, and gateway-carried settings validate against the daemon
  contract.
- A2A and MCP protocol plugins can register daemon route keys using the shared
  dispatch helpers.
- `silvaengine_gateway` can load its own route manifest and route external
  requests to the `silvaengine_daemon` entry point.
- `silvaengine_daemon` can resolve each request to the configured plugin module
  and dispatch function.
- PostgreSQL RLS setup and scoped-session teardown are covered by tests.
- Old project behavior has a migration path with route-compatible shims or a
  documented gateway manifest update.

## Risks

| Risk | Mitigation |
| --- | --- |
| Shared base grows into a protocol-aware package. | Enforce dependency boundaries in `pyproject.toml` and tests. |
| Entity models are similar but not identical. | Share repository interfaces first; defer shared entities until duplication is proven harmful. |
| Gateway route changes break clients. | Keep external paths stable and verify the `silvaengine_gateway` -> `silvaengine_daemon` -> plugin dispatch chain in one release. |
| SSE semantics differ by protocol. | Share only connection/fan-out mechanics; keep event schema in protocol plugins. |
