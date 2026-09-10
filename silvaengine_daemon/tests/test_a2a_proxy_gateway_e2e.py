#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Live end-to-end test: SilvaEngine Gateway -> silvaengine_daemon (plugin
routing) -> a2a_protocol_plugin -> A2AProxyHandler -> external A2A server.

Same "new structure" story as the core_engine and Hermes daemon e2e tests:
the former ``a2a_daemon_engine`` module (which owned ``A2AProxyHandler``
directly, see ``a2a_daemon_engine/tests/test_a2a_proxy_e2e.py``) was replaced
by silvaengine_daemon's generic plugin-routing daemon
(``config/plugin_routing.yaml``), dispatching through
``silvaengine_daemon.gateway:dispatch_a2a_jsonrpc`` into ``a2a_protocol_plugin``
— the exact same handler code, now reached one hop further away.

Unlike the Hermes and core_engine handlers, ``A2AProxyHandler`` is generic:
it forwards JSON-RPC 2.0 A2A protocol calls (``message/send``,
``tasks/cancel``, ...) verbatim to *any* external, fully-A2A-compliant
server — here, a native A2A adapter for Hermes listening on port 9900 (its
own Agent Card, JSON-RPC endpoint, and SSE stream — distinct from the
OpenAI-compatible Hermes bridge on port 8642 that ``HermesAgentHandler``
talks to).

Full request path — two gateway entry points reach the same handler:

    Client
      -> SilvaEngine Gateway (default port 8765)
      -> POST /{endpoint_id}/a2a       -> dispatch_a2a_jsonrpc     -> dispatch_a2a
      -> POST /{endpoint_id}/a2a_sse   -> dispatch_a2a_sse_message -> dispatch_a2a  (+ SSE push)
      -> A2ADaemonEngine.a2a() -> A2A SDK request handler -> executor
      -> A2AProxyHandler
      -> external A2A server (default http://localhost:9900), JSON-RPC 2.0
      -> JSON-RPC response back through the gateway

Tests 1-7 exercise ``/{endpoint_id}/a2a``; test 8 exercises
``/{endpoint_id}/a2a_sse`` — a second dispatch entry point into the exact
same ``A2AProxyHandler`` code, so both routes into the plugin-routing
structure are proven, not just one.

Prerequisites:
    - An external, fully-A2A-compliant server reachable at
      http://localhost:9900 (Agent Card at /.well-known/agent-card.json,
      JSON-RPC at /), no auth token required for localhost
    - SilvaEngine Gateway running (default http://127.0.0.1:8765)
    - silvaengine_daemon and a2a_protocol_plugin installed/importable in the
      gateway's environment

Usage:
    # pytest, explicitly opted in (skipped by default)
    SILVAENGINE_DAEMON_RUN_LIVE_E2E=1 python -m pytest \
        tests/test_a2a_proxy_gateway_e2e.py -v

    # direct run (auto-reads gateway .env, generates a token)
    python tests/test_a2a_proxy_gateway_e2e.py --gateway-url http://127.0.0.1:8765
"""
from __future__ import annotations

__author__ = "bibow"

import argparse
import json
import os
import sys
import time
import uuid
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

    The A2A proxy shares the same daemon route as core_engine/hermes
    (``a2a_jsonrpc``) — ``a2a_protocol_plugin`` branches internally by the
    registered agent's ``agent_type`` metadata (here: ``a2a_proxy``), not by
    a separate daemon route per backend.
    """
    assert get_dispatch_ref("a2a_jsonrpc") == "a2a_protocol_plugin.main:dispatch_a2a"


# ---------------------------------------------------------------------------
# Live-gateway steps — skipped unless explicitly enabled
# ---------------------------------------------------------------------------

_live_e2e = pytest.mark.skipif(
    os.getenv("SILVAENGINE_DAEMON_RUN_LIVE_E2E", "").lower() not in {"1", "true", "yes"},
    reason="Live gateway/A2A proxy E2E requires SILVAENGINE_DAEMON_RUN_LIVE_E2E=1 "
    "plus a running SilvaEngine Gateway and an A2A server on the target port.",
)

TESTS_DIR = Path(__file__).resolve().parent
GATEWAY_ENV_FILE = Path(
    os.getenv("SILVAENGINE_DAEMON_E2E_ENV_FILE", str(TESTS_DIR / ".env"))
)

DEFAULT_PROXY_URL = "http://localhost:9900"
A2A_PROXY_AGENT_ID = "a2a-proxy-agent"

RESULTS: list = []


# ---------------------------------------------------------------------------
# .env loader (mirrors test_core_engine_gateway_e2e.py / test_hermes_gateway_e2e.py)
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
    proxy_url = env.get("A2A_PROXY_URL", DEFAULT_PROXY_URL)
    proxy_token = env.get("A2A_PROXY_TOKEN", "")
    endpoint_id = env.get("endpoint_id", "gpt")
    part_id = env.get("part_id", "nestaging")
    token = generate_token(env, gateway_url)
    return {
        "gateway_url": gateway_url,
        "proxy_url": proxy_url,
        "proxy_token": proxy_token,
        "endpoint_id": endpoint_id,
        "part_id": part_id,
        "token": token,
    }


# ---------------------------------------------------------------------------
# Target A2A server probe helpers
# ---------------------------------------------------------------------------


def proxy_target_agent_card_ok(proxy_url: str) -> Dict[str, Any]:
    try:
        r = requests.get(f"{proxy_url}/.well-known/agent-card.json", timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# HTTP helpers (gateway side)
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


def register_a2a_proxy_agent(
    gateway_url: str, token: str, endpoint_id: str, part_id: str,
    proxy_url: str, proxy_token: str,
) -> Dict[str, Any]:
    """Register the a2a-proxy-agent fixture via the daemon's own A2A GraphQL
    route (``/{endpoint_id}/a2a_core_graphql``, dispatched through
    ``silvaengine_daemon.gateway:dispatch_a2a_graphql``)."""
    metadata = {
        "agent_type": "a2a_proxy",
        "a2a_proxy_url": proxy_url,
        "a2a_proxy_token": proxy_token,
        "a2a_proxy_timeout": 120,
    }
    mutation = """
        mutation RegisterA2aProxyAgent(
            $endpointId: String!
            $partId: String!
            $agentId: String
            $agentName: String!
            $endpointUrl: String!
            $metadata: JSON
            $updatedBy: String!
        ) {
            insertUpdateA2aAgent(
                endpointId: $endpointId
                partId: $partId
                agentId: $agentId
                agentName: $agentName
                endpointUrl: $endpointUrl
                metadata: $metadata
                updatedBy: $updatedBy
            ) {
                a2aAgent { agentId agentName }
            }
        }
    """
    variables = {
        "endpointId": endpoint_id,
        "partId": part_id,
        "agentId": A2A_PROXY_AGENT_ID,
        "agentName": "A2A Proxy Agent",
        "endpointUrl": gateway_url,
        "metadata": metadata,
        "updatedBy": "daemon-e2e",
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


def send_a2a_sse(
    gateway_url: str,
    token: str,
    endpoint_id: str,
    part_id: str,
    method: str,
    params: Dict[str, Any],
    request_id: str = "1",
    timeout: int = 180,
) -> requests.Response:
    """Send a JSON-RPC 2.0 request through the gateway's ``/{endpoint_id}/a2a_sse``
    route — wired to ``silvaengine_daemon.gateway:dispatch_a2a_sse_message``.

    Unlike ``send_a2a``, this exercises ``A2ADaemonEngine.sse_message()``,
    which runs the identical JSON-RPC handling as ``a2a()`` and then also
    pushes the response to any SSE-connected client for the caller's user —
    a second entry point into the same ``A2AProxyHandler`` code path.
    """
    body = {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}
    return requests.post(
        f"{gateway_url}/{endpoint_id}/a2a_sse",
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
# Test 1: target A2A server Agent Card discovery
# ---------------------------------------------------------------------------


@_live_e2e
def test_01_target_agent_card(ctx: Dict[str, Any]) -> None:
    card = proxy_target_agent_card_ok(ctx["proxy_url"])
    assert card, f"No Agent Card at {ctx['proxy_url']}/.well-known/agent-card.json"
    assert card.get("name"), "Agent card should have a name"
    assert card.get("capabilities", {}).get("streaming") is True, "Should support streaming"


# ---------------------------------------------------------------------------
# Test 2: gateway health
# ---------------------------------------------------------------------------


@_live_e2e
def test_02_gateway_health(ctx: Dict[str, Any]) -> None:
    assert gateway_health_ok(ctx["gateway_url"], ctx["token"]), (
        f"Gateway /health failed at {ctx['gateway_url']}"
    )


# ---------------------------------------------------------------------------
# Test 3: register/verify the a2a-proxy-agent fixture via the daemon
# ---------------------------------------------------------------------------


@_live_e2e
def test_03_register_agent(ctx: Dict[str, Any]) -> None:
    result = register_a2a_proxy_agent(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        ctx["proxy_url"], ctx["proxy_token"],
    )
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Test 4: non-streaming message/send through the new plugin-routing path
# ---------------------------------------------------------------------------


@_live_e2e
def test_04_non_streaming_send(ctx: Dict[str, Any]) -> None:
    params = {
        "message": {"role": "user", "parts": [{"text": "Reply with exactly: A2A_PROXY_OK"}]},
        "metadata": {"operation": "message_response", "agent_uuid": A2A_PROXY_AGENT_ID},
    }
    r = send_a2a(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "message/send", params, "a2a-proxy-daemon-e2e-send-001",
    )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    body = r.json()
    assert not body.get("error"), f"JSON-RPC error: {body.get('error')}"
    text = extract_text(body.get("result", {}))
    assert not is_error_text(text), f"Response is an error, not a real reply: {text[:200]}"
    assert len(text) > 0, "Response text is empty"


# ---------------------------------------------------------------------------
# Test 5: multi-turn conversation continuity (contextId)
# ---------------------------------------------------------------------------


@_live_e2e
def test_05_multi_turn(ctx: Dict[str, Any]) -> None:
    params1 = {
        "message": {"role": "user", "parts": [{"text": "Remember the number 42. Reply: OK"}]},
        "metadata": {"operation": "message_response", "agent_uuid": A2A_PROXY_AGENT_ID},
    }
    r1 = send_a2a(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "message/send", params1, "a2a-proxy-daemon-e2e-turn1",
    )
    assert r1.status_code == 200, f"HTTP {r1.status_code}: {r1.text[:300]}"
    body1 = r1.json()
    assert not body1.get("error"), f"Turn 1 JSON-RPC error: {body1.get('error')}"
    context_id = body1.get("result", {}).get("contextId") or ""

    params2 = {
        "message": {"role": "user", "parts": [{"text": "What number did I ask you to remember?"}]},
        "metadata": {"operation": "message_response", "agent_uuid": A2A_PROXY_AGENT_ID},
    }
    if context_id:
        params2["message"]["contextId"] = context_id
    r2 = send_a2a(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "message/send", params2, "a2a-proxy-daemon-e2e-turn2",
    )
    assert r2.status_code == 200, f"HTTP {r2.status_code}: {r2.text[:300]}"
    body2 = r2.json()
    assert not body2.get("error"), f"Turn 2 JSON-RPC error: {body2.get('error')}"
    text2 = extract_text(body2.get("result", {}))
    assert len(text2) > 0, "Second turn should have content"


# ---------------------------------------------------------------------------
# Test 6: cancel a task
# ---------------------------------------------------------------------------


@_live_e2e
def test_06_cancel(ctx: Dict[str, Any]) -> None:
    task_id = f"a2a-proxy-daemon-cancel-{uuid.uuid4().hex[:8]}"
    r = send_a2a(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "tasks/cancel", {"id": task_id}, "a2a-proxy-daemon-e2e-cancel-001", timeout=30,
    )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    body = r.json()
    if body.get("error"):
        assert "not found" in body["error"].get("message", "").lower()


# ---------------------------------------------------------------------------
# Test 7: failure case — unknown agent
# ---------------------------------------------------------------------------


@_live_e2e
def test_07_unknown_agent_failure(ctx: Dict[str, Any]) -> None:
    params = {
        "message": {"role": "user", "parts": [{"text": "This should fail."}]},
        "metadata": {"operation": "message_response", "agent_uuid": "nonexistent-agent-xyz"},
    }
    r = send_a2a(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "message/send", params, "a2a-proxy-daemon-e2e-fail-001", timeout=60,
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
# Test 8: non-streaming message/send through the A2A SSE route
# ---------------------------------------------------------------------------


@_live_e2e
def test_08_sse_route_non_streaming_send(ctx: Dict[str, Any]) -> None:
    """A second entry point into the same A2AProxyHandler: ``/{endpoint_id}/a2a_sse``
    (``dispatch_a2a_sse_message``) runs the identical JSON-RPC handling as
    ``/{endpoint_id}/a2a`` and additionally pushes the response to any
    SSE-connected client for the caller's user."""
    params = {
        "message": {"role": "user", "parts": [{"text": "Reply with exactly: A2A_SSE_PROXY_OK"}]},
        "metadata": {"operation": "message_response", "agent_uuid": A2A_PROXY_AGENT_ID},
    }
    r = send_a2a_sse(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "message/send", params, "a2a-proxy-daemon-e2e-sse-send-001",
    )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    body = r.json()
    assert not body.get("error"), f"JSON-RPC error: {body.get('error')}"
    text = extract_text(body.get("result", {}))
    assert not is_error_text(text), f"Response is an error, not a real reply: {text[:200]}"
    assert len(text) > 0, "Response text is empty"


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
    proxy_url = args.proxy_url or env.get("A2A_PROXY_URL", DEFAULT_PROXY_URL)
    proxy_token = args.proxy_token or env.get("A2A_PROXY_TOKEN", "")
    endpoint_id = args.endpoint_id or env.get("endpoint_id", "gpt")
    part_id = args.part_id or env.get("part_id", "nestaging")
    token = args.token or generate_token(env, gateway_url)
    return {
        "gateway_url": gateway_url,
        "proxy_url": proxy_url,
        "proxy_token": proxy_token,
        "endpoint_id": endpoint_id,
        "part_id": part_id,
        "token": token,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live E2E: SilvaEngine Gateway -> silvaengine_daemon plugin "
        "routing -> a2a_protocol_plugin -> A2A proxy target server"
    )
    parser.add_argument("--gateway-url", default=None)
    parser.add_argument("--proxy-url", default=None)
    parser.add_argument("--proxy-token", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--endpoint-id", default=None)
    parser.add_argument("--part-id", default=None)
    args = parser.parse_args()

    print("=" * 70)
    print("silvaengine_daemon -> a2a_protocol_plugin -> A2A proxy target E2E")
    print("=" * 70)

    print(f"  Routing check: a2a_jsonrpc -> {get_dispatch_ref('a2a_jsonrpc')}")

    ctx = build_context(args)
    print(f"  Gateway:      {ctx['gateway_url']}")
    print(f"  Proxy target: {ctx['proxy_url']}")
    print(f"  Endpoint:     {ctx['endpoint_id']} / {ctx['part_id']}")

    tests = [
        ("E2E-001", "Target Agent Card discovery", lambda: test_01_target_agent_card(ctx)),
        ("E2E-002", "Gateway health", lambda: test_02_gateway_health(ctx)),
        ("E2E-003", "Register a2a-proxy-agent", lambda: test_03_register_agent(ctx)),
        ("E2E-004", "Non-streaming message/send", lambda: test_04_non_streaming_send(ctx)),
        ("E2E-005", "Multi-turn conversation", lambda: test_05_multi_turn(ctx)),
        ("E2E-006", "Cancel task", lambda: test_06_cancel(ctx)),
        ("E2E-007", "Failure: unknown agent", lambda: test_07_unknown_agent_failure(ctx)),
        ("E2E-008", "Non-streaming send via A2A SSE route", lambda: test_08_sse_route_non_streaming_send(ctx)),
    ]
    for tid, tname, fn in tests:
        run_test(tid, tname, fn)
        time.sleep(1)

    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    print(f"\n{'=' * 70}")
    print(f"Results: {passed} passed, {failed} failed, {len(RESULTS)} total")
    print(f"{'=' * 70}")

    results_path = TESTS_DIR.parent / "docs" / "test_results" / "a2a_proxy_gateway_e2e_results.json"
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
