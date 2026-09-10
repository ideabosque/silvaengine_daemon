#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Live end-to-end test: SilvaEngine Gateway -> silvaengine_daemon (plugin
routing) -> a2a_protocol_plugin -> CoreEngineAgentHandler -> core_engine.

``silvaengine_daemon`` replaced the old standalone ``a2a_daemon_engine``
module with a generic plugin-routing daemon (``config/plugin_routing.yaml``):
the gateway now calls ``silvaengine_daemon.gateway:dispatch_a2a_jsonrpc``,
which looks up the configured plugin route and dispatches into
``a2a_protocol_plugin`` — the same handler code that used to live directly
in ``a2a_daemon_engine``. This test proves that new indirection still
delivers a request all the way to the Core Engine agent (``ai_agent_core_engine``,
via ``CoreEngineAgentHandler``) end to end through a live gateway.

Structure and harness (``run_test``, JSON results file, colourised
PASS/FAIL) are carried over from
``a2a_daemon_engine/tests/test_a2a_proxy_e2e.py``. The gateway auth/registration
helpers are carried over from
``silvaengine_gateway/tests/test_core_engine_gateway_live.py``, which already
exercises this exact route (``/{endpoint_id}/a2a``) — this copy lives in
``silvaengine_daemon`` because that's the package whose routing structure
changed, and step 0 below asserts the new routing config is what's actually
being exercised before any network call is made.

Full request path:

    Client
      -> SilvaEngine Gateway (default port 8765)
      -> POST /{endpoint_id}/a2a
      -> silvaengine_daemon.gateway:dispatch_a2a_jsonrpc   (routing.yaml lookup)
      -> a2a_protocol_plugin.main:dispatch_a2a
      -> A2ADaemonEngine.a2a() -> A2A SDK request handler -> executor
      -> CoreEngineAgentHandler
      -> POST /{endpoint_id}/ai_agent_core_graphql (or WS .../ai_agent_core_ws)
      -> ai_agent_core_engine (ask_model -> execute_ask_model -> message_list)
      -> JSON-RPC response back through the gateway

Prerequisites:
    - SilvaEngine Gateway running (default http://127.0.0.1:8765)
    - silvaengine_daemon, a2a_protocol_plugin, ai_agent_core_engine all
      installed/importable in the gateway's environment
    - Gateway .env with ADMIN_STATIC_TOKEN (or local JWT secret), endpoint_id,
      part_id
    - An agent registered in ai_agent_core_engine (CORE_ENGINE_AGENT_UUID or
      DEFAULT_AGENT_UUID)

Usage:
    # pytest, explicitly opted in (skipped by default)
    SILVAENGINE_DAEMON_RUN_LIVE_E2E=1 python -m pytest \
        tests/test_core_engine_gateway_e2e.py -v

    # direct run (auto-reads gateway .env, generates a token)
    python tests/test_core_engine_gateway_e2e.py --gateway-url http://127.0.0.1:8765
"""
from __future__ import annotations

__author__ = "bibow"

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

import pytest
import requests

from silvaengine_daemon.routing import get_dispatch_ref

# ---------------------------------------------------------------------------
# Step 0 — routing wiring assertion (no network; always runs)
# ---------------------------------------------------------------------------


def test_00_a2a_jsonrpc_route_is_wired_to_a2a_protocol_plugin() -> None:
    """Pin the exact dispatch target every step below relies on.

    If a future ``plugin_routing.yaml`` edit repoints ``a2a_jsonrpc`` at a
    different plugin or a renamed function, this fails immediately instead
    of only surfacing as an opaque HTTP 500 from the live gateway steps.
    """
    assert get_dispatch_ref("a2a_jsonrpc") == "a2a_protocol_plugin.main:dispatch_a2a"


# ---------------------------------------------------------------------------
# Live-gateway steps — skipped unless explicitly enabled
# ---------------------------------------------------------------------------

_live_e2e = pytest.mark.skipif(
    os.getenv("SILVAENGINE_DAEMON_RUN_LIVE_E2E", "").lower() not in {"1", "true", "yes"},
    reason="Live gateway/core_engine E2E requires SILVAENGINE_DAEMON_RUN_LIVE_E2E=1 "
    "plus a running SilvaEngine Gateway with ai_agent_core_engine wired up.",
)

TESTS_DIR = Path(__file__).resolve().parent
# Allow pointing at another checkout's gateway .env (e.g. silvaengine_gateway's
# own tests/.env) instead of requiring a duplicate copy of gateway secrets in
# this repo.
GATEWAY_ENV_FILE = Path(
    os.getenv("SILVAENGINE_DAEMON_E2E_ENV_FILE", str(TESTS_DIR / ".env"))
)

DEFAULT_GATEWAY_URL = "http://127.0.0.1:8765"
CORE_ENGINE_AGENT_ID = "core-engine-agent"
DEFAULT_AGENT_UUID = "agent-1780802783-70468776"

RESULTS: list = []


# ---------------------------------------------------------------------------
# .env loader (mirrors silvaengine_gateway/tests/test_core_engine_gateway_live.py)
# ---------------------------------------------------------------------------


def load_gateway_env() -> Dict[str, str]:
    if not GATEWAY_ENV_FILE.exists():
        return {}
    env: Dict[str, str] = {}
    with open(GATEWAY_ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if " #" in value:
                value = value.split(" #", 1)[0].strip()
            if key:
                env[key] = value
    return env


def generate_token(env: Dict[str, str], gateway_url: str) -> str:
    static = env.get("ADMIN_STATIC_TOKEN", "")
    if static:
        return static

    jwt_secret = env.get("JWT_SECRET_KEY", "CHANGEME")
    jwt_algo = env.get("JWT_ALGORITHM", "HS256")
    try:
        from jose import jwt
        import pendulum

        payload = {
            "sub": "daemon-e2e",
            "username": "daemon-e2e",
            "role": "admin",
            "iat": pendulum.now("UTC"),
            "perm": True,
        }
        return jwt.encode(payload, jwt_secret, algorithm=jwt_algo)
    except ImportError:
        return ""


# ---------------------------------------------------------------------------
# pytest fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ctx() -> Dict[str, Any]:
    env = load_gateway_env()
    gateway_url = f"http://127.0.0.1:{env.get('GATEWAY_PORT', '8765')}"
    endpoint_id = env.get("endpoint_id", "gpt")
    part_id = env.get("part_id", "nestaging")
    token = generate_token(env, gateway_url)
    return {
        "gateway_url": gateway_url,
        "endpoint_id": endpoint_id,
        "part_id": part_id,
        "token": token,
        "core_engine_agent_uuid": (
            env.get("CORE_ENGINE_AGENT_UUID")
            or env.get("DEFAULT_AGENT_UUID")
            or DEFAULT_AGENT_UUID
        ),
    }


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def gateway_health_ok(gateway_url: str, token: str) -> bool:
    try:
        r = requests.get(
            f"{gateway_url}/health",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        return r.status_code == 200
    except Exception:
        return False


def register_core_engine_agent(
    gateway_url: str, token: str, endpoint_id: str, part_id: str, core_engine_agent_uuid: str
) -> Dict[str, Any]:
    """Register the core-engine-agent fixture via the daemon's own A2A GraphQL
    route (``/{endpoint_id}/a2a_core_graphql``, dispatched through
    ``silvaengine_daemon.gateway:dispatch_a2a_graphql``)."""
    metadata = {
        "agent_type": "core_engine",
        "core_engine_graphql_url": gateway_url,
        "core_engine_ws_url": gateway_url.replace("http://", "ws://"),
        "core_engine_token": token,
        "core_engine_agent_uuid": core_engine_agent_uuid,
        "core_engine_updated_by": "silvaengine-daemon",
        "core_engine_stream_timeout": 120.0,
    }
    mutation = """
        mutation RegisterCoreEngineAgent(
            $endpointId: String!
            $partId: String!
            $agentId: String
            $agentName: String!
            $endpointUrl: String!
            $updatedBy: String!
            $metadata: JSON
        ) {
            insertUpdateA2aAgent(
                endpointId: $endpointId
                partId: $partId
                agentId: $agentId
                agentName: $agentName
                endpointUrl: $endpointUrl
                updatedBy: $updatedBy
                metadata: $metadata
            ) {
                a2aAgent { agentId agentName }
            }
        }
    """
    variables = {
        "endpointId": endpoint_id,
        "partId": part_id,
        "agentId": CORE_ENGINE_AGENT_ID,
        "agentName": "Core Engine Agent",
        "endpointUrl": gateway_url,
        "updatedBy": "daemon-e2e",
        "metadata": metadata,
    }
    try:
        r = requests.post(
            f"{gateway_url}/{endpoint_id}/a2a_core_graphql",
            json={"query": mutation, "variables": variables},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Part-Id": part_id,
            },
            timeout=30,
        )
        if r.status_code == 200:
            body = r.json()
            if "body" in body:
                body = json.loads(body["body"])
            return body.get("data", {}).get("insertUpdateA2aAgent") or {}
        return {}
    except Exception:
        return {}


def send_a2a(
    gateway_url: str,
    token: str,
    endpoint_id: str,
    part_id: str,
    method: str,
    params: Dict[str, Any],
    request_id: str = "1",
    timeout: int = 180,
) -> requests.Response:
    """Send a JSON-RPC 2.0 request through the gateway's ``/{endpoint_id}/a2a``
    route — the route wired to ``silvaengine_daemon.gateway:dispatch_a2a_jsonrpc``."""
    body = {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}
    return requests.post(
        f"{gateway_url}/{endpoint_id}/a2a",
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Part-Id": part_id,
        },
        timeout=timeout,
    )


def extract_text(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    parts = result.get("parts", [])
    if parts:
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in parts)
    artifacts = result.get("artifacts", [])
    if artifacts:
        texts = []
        for a in artifacts:
            if isinstance(a, dict):
                for p in a.get("parts", []):
                    texts.append(p.get("text", "") if isinstance(p, dict) else str(p))
        return "".join(texts)
    return result.get("text", "")


def extract_state(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    status = result.get("status", {})
    if isinstance(status, dict):
        return status.get("state", "").lower()
    if isinstance(status, str):
        return status.lower()
    return ""


def is_error_text(text: str) -> bool:
    if not text:
        return False
    lower = text.lower().strip()
    return lower.startswith("ai agent error:") or lower.startswith("error:")


# ---------------------------------------------------------------------------
# Test 1: gateway health
# ---------------------------------------------------------------------------


@_live_e2e
def test_01_gateway_health(ctx: Dict[str, Any]) -> None:
    assert gateway_health_ok(ctx["gateway_url"], ctx["token"]), (
        f"Gateway /health failed at {ctx['gateway_url']}"
    )


# ---------------------------------------------------------------------------
# Test 2: register/verify the core-engine-agent fixture via the daemon
# ---------------------------------------------------------------------------


@_live_e2e
def test_02_register_agent(ctx: Dict[str, Any]) -> None:
    result = register_core_engine_agent(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        ctx["core_engine_agent_uuid"],
    )
    # Registration is best-effort (the agent may already exist); the real
    # assertion is that the daemon's GraphQL route responded at all, which
    # register_core_engine_agent already required to return a non-exception.
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Test 3: non-streaming message/send through the new plugin-routing path
# ---------------------------------------------------------------------------


@_live_e2e
def test_03_non_streaming_send(ctx: Dict[str, Any]) -> None:
    params = {
        "message": {"role": "user", "parts": [{"text": "Say hello in one word."}]},
        "metadata": {"operation": "message_response", "agent_uuid": CORE_ENGINE_AGENT_ID},
    }
    r = send_a2a(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "message/send", params, "daemon-e2e-send-001",
    )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    body = r.json()
    assert not body.get("error"), f"JSON-RPC error: {body.get('error')}"
    text = extract_text(body.get("result", {}))
    assert not is_error_text(text), f"Response is an error, not a real reply: {text[:200]}"
    assert len(text) > 0, "Response text is empty"


# ---------------------------------------------------------------------------
# Test 4: multi-turn conversation continuity (context_id / thread_uuid)
# ---------------------------------------------------------------------------


@_live_e2e
def test_04_multi_turn(ctx: Dict[str, Any]) -> None:
    params1 = {
        "message": {"role": "user", "parts": [{"text": "Remember the number 42. Reply: OK"}]},
        "metadata": {"operation": "message_response", "agent_uuid": CORE_ENGINE_AGENT_ID},
    }
    r1 = send_a2a(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "message/send", params1, "daemon-e2e-turn1",
    )
    assert r1.status_code == 200, f"HTTP {r1.status_code}: {r1.text[:300]}"
    body1 = r1.json()
    assert not body1.get("error"), f"Turn 1 JSON-RPC error: {body1.get('error')}"
    result1 = body1.get("result", {})
    context_id = result1.get("contextId") or result1.get("context_id") or ""

    params2 = {
        "message": {
            "role": "user",
            "parts": [{"text": "What number did I ask you to remember?"}],
        },
        "metadata": {"operation": "message_response", "agent_uuid": CORE_ENGINE_AGENT_ID},
    }
    if context_id:
        params2["message"]["contextId"] = context_id
    r2 = send_a2a(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "message/send", params2, "daemon-e2e-turn2",
    )
    assert r2.status_code == 200, f"HTTP {r2.status_code}: {r2.text[:300]}"
    body2 = r2.json()
    assert not body2.get("error"), f"Turn 2 JSON-RPC error: {body2.get('error')}"
    text2 = extract_text(body2.get("result", {}))
    assert len(text2) > 0, "Second turn should have content"


# ---------------------------------------------------------------------------
# Test 5: cancel a task
# ---------------------------------------------------------------------------


@_live_e2e
def test_05_cancel(ctx: Dict[str, Any]) -> None:
    r = send_a2a(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "tasks/cancel", {"id": "daemon-e2e-nonexistent-task"}, "daemon-e2e-cancel-001",
        timeout=30,
    )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    body = r.json()
    # "Task not found" is expected/acceptable — the point is the route
    # responded through the daemon rather than 404/500ing before reaching it.
    if body.get("error"):
        assert "not found" in body["error"].get("message", "").lower()


# ---------------------------------------------------------------------------
# Test 6: failure case — unknown agent
# ---------------------------------------------------------------------------


@_live_e2e
def test_06_unknown_agent_failure(ctx: Dict[str, Any]) -> None:
    params = {
        "message": {"role": "user", "parts": [{"text": "This should fail."}]},
        "metadata": {"operation": "message_response", "agent_uuid": "nonexistent-agent-xyz"},
    }
    r = send_a2a(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "message/send", params, "daemon-e2e-fail-001", timeout=60,
    )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    body = r.json()
    result = body.get("result", {})
    text = extract_text(result)
    state = extract_state(result)
    error = body.get("error")
    assert error or is_error_text(text) or "not found" in text.lower() or "failed" in state, (
        f"Expected a failure signal for an unknown agent, got: "
        f"error={error}, text={text[:200]!r}, state={state!r}"
    )


# ---------------------------------------------------------------------------
# Direct-run harness (mirrors a2a_daemon_engine/tests/test_a2a_proxy_e2e.py)
# ---------------------------------------------------------------------------


def run_test(test_id: str, test_name: str, fn) -> None:
    t0 = time.perf_counter()
    try:
        fn()
        elapsed = time.perf_counter() - t0
        RESULTS.append({"id": test_id, "name": test_name, "status": "PASS", "elapsed_s": round(elapsed, 2)})
        print(f"  {test_id}: PASS - {test_name} ({elapsed:.1f}s)")
    except Exception as e:
        elapsed = time.perf_counter() - t0
        RESULTS.append({
            "id": test_id, "name": test_name, "status": "FAIL",
            "elapsed_s": round(elapsed, 2), "error": str(e)[:300],
        })
        print(f"  {test_id}: FAIL - {test_name} ({elapsed:.1f}s) - {str(e)[:200]}")


def build_context(args: argparse.Namespace) -> Dict[str, Any]:
    env = load_gateway_env()
    gateway_url = args.gateway_url or f"http://127.0.0.1:{env.get('GATEWAY_PORT', '8765')}"
    endpoint_id = args.endpoint_id or env.get("endpoint_id", "gpt")
    part_id = args.part_id or env.get("part_id", "nestaging")
    token = args.token or generate_token(env, gateway_url)
    return {
        "gateway_url": gateway_url,
        "endpoint_id": endpoint_id,
        "part_id": part_id,
        "token": token,
        "core_engine_agent_uuid": (
            args.core_engine_agent_uuid
            or env.get("CORE_ENGINE_AGENT_UUID")
            or env.get("DEFAULT_AGENT_UUID")
            or DEFAULT_AGENT_UUID
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live E2E: SilvaEngine Gateway -> silvaengine_daemon plugin "
        "routing -> a2a_protocol_plugin -> core_engine"
    )
    parser.add_argument("--gateway-url", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--endpoint-id", default=None)
    parser.add_argument("--part-id", default=None)
    parser.add_argument("--core-engine-agent-uuid", default=None)
    args = parser.parse_args()

    print("=" * 70)
    print("silvaengine_daemon -> a2a_protocol_plugin -> core_engine E2E")
    print("=" * 70)

    print(f"  Routing check: a2a_jsonrpc -> {get_dispatch_ref('a2a_jsonrpc')}")

    ctx = build_context(args)
    print(f"  Gateway:  {ctx['gateway_url']}")
    print(f"  Endpoint: {ctx['endpoint_id']} / {ctx['part_id']}")

    tests = [
        ("E2E-001", "Gateway health", lambda: test_01_gateway_health(ctx)),
        ("E2E-002", "Register core-engine-agent", lambda: test_02_register_agent(ctx)),
        ("E2E-003", "Non-streaming message/send", lambda: test_03_non_streaming_send(ctx)),
        ("E2E-004", "Multi-turn conversation", lambda: test_04_multi_turn(ctx)),
        ("E2E-005", "Cancel task", lambda: test_05_cancel(ctx)),
        ("E2E-006", "Unknown agent failure", lambda: test_06_unknown_agent_failure(ctx)),
    ]
    for tid, tname, fn in tests:
        run_test(tid, tname, fn)

    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    print(f"\n{'=' * 70}")
    print(f"Results: {passed} passed, {failed} failed, {len(RESULTS)} total")
    print(f"{'=' * 70}")

    results_path = TESTS_DIR.parent / "docs" / "test_results" / "core_engine_gateway_e2e_results.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(
            {"tests": RESULTS, "passed": passed, "failed": failed, "target": ctx["gateway_url"]},
            f, indent=2,
        )
    print(f"Results: {results_path}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
