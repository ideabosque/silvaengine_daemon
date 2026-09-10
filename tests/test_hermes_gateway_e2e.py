#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Live end-to-end test: SilvaEngine Gateway -> silvaengine_daemon (plugin
routing) -> a2a_protocol_plugin -> HermesAgentHandler -> Hermes Agent bridge.

Same "new structure" story as ``test_core_engine_gateway_e2e.py``: the
former ``a2a_daemon_engine`` module (which owned ``HermesAgentHandler``
directly) was replaced by silvaengine_daemon's generic plugin-routing daemon
(``config/plugin_routing.yaml``), dispatching through
``silvaengine_daemon.gateway:dispatch_a2a_jsonrpc`` into ``a2a_protocol_plugin``
— the exact same handler code, now reached one hop further away. This test
proves that indirection still delivers a request all the way to the Hermes
Agent bridge end to end through a live gateway.

Structure and harness (``run_test``, JSON results file, colourised
PASS/FAIL) are carried over from
``a2a_daemon_engine/tests/test_a2a_proxy_e2e.py``. The Hermes probe/auth/
registration helpers are carried over from
``silvaengine_gateway/tests/test_hermes_gateway_live.py``, which already
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
      -> HermesAgentHandler
      -> Hermes Agent bridge (OpenAI-compatible API, default http://127.0.0.1:8642)
      -> JSON-RPC response back through the gateway

Prerequisites:
    - Hermes Agent bridge running (default http://127.0.0.1:8642), reachable
      at /health and /v1/models with API_SERVER_KEY auth — this is the
      "harness/hermes agent bridge", NOT the a2a_protocol_plugin A2A SDK
      layer, and NOT run via this repo's docker-hermes-agent compose file
      when it's already running as a bare local process.
    - SilvaEngine Gateway running (default http://127.0.0.1:8765)
    - silvaengine_daemon and a2a_protocol_plugin installed/importable in the
      gateway's environment
    - Gateway .env with ADMIN_STATIC_TOKEN (or local JWT secret), endpoint_id,
      part_id, HERMES_API_URL, HERMES_API_KEY, HERMES_MODEL

Usage:
    # pytest, explicitly opted in (skipped by default)
    SILVAENGINE_DAEMON_RUN_LIVE_E2E=1 python -m pytest \
        tests/test_hermes_gateway_e2e.py -v

    # direct run (auto-reads gateway .env, generates a token)
    python tests/test_hermes_gateway_e2e.py --gateway-url http://127.0.0.1:8765
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

    Hermes shares the same daemon route as core_engine (``a2a_jsonrpc``) —
    ``a2a_protocol_plugin`` branches internally by the registered agent's
    ``agent_type`` metadata (hermes / core_engine / openclaw), not by a
    separate daemon route per backend.
    """
    assert get_dispatch_ref("a2a_jsonrpc") == "a2a_protocol_plugin.main:dispatch_a2a"


# ---------------------------------------------------------------------------
# Live-gateway steps — skipped unless explicitly enabled
# ---------------------------------------------------------------------------

_live_e2e = pytest.mark.skipif(
    os.getenv("SILVAENGINE_DAEMON_RUN_LIVE_E2E", "").lower() not in {"1", "true", "yes"},
    reason="Live gateway/Hermes E2E requires SILVAENGINE_DAEMON_RUN_LIVE_E2E=1 "
    "plus a running SilvaEngine Gateway with the Hermes Agent bridge reachable.",
)

TESTS_DIR = Path(__file__).resolve().parent
GATEWAY_ENV_FILE = Path(
    os.getenv("SILVAENGINE_DAEMON_E2E_ENV_FILE", str(TESTS_DIR / ".env"))
)

DEFAULT_HERMES_URL = "http://127.0.0.1:8642"
HERMES_AGENT_ID = "hermes-agent"

RESULTS: list = []


# ---------------------------------------------------------------------------
# .env loader (mirrors test_core_engine_gateway_e2e.py)
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
    hermes_url = env.get("HERMES_API_URL", DEFAULT_HERMES_URL)
    hermes_key = env.get("HERMES_API_KEY", "")
    hermes_model = env.get("HERMES_MODEL", "hermes-agent")
    endpoint_id = env.get("endpoint_id", "gpt")
    part_id = env.get("part_id", "nestaging")
    token = generate_token(env, gateway_url)
    return {
        "gateway_url": gateway_url,
        "hermes_url": hermes_url,
        "hermes_key": hermes_key,
        "hermes_model": hermes_model,
        "endpoint_id": endpoint_id,
        "part_id": part_id,
        "token": token,
    }


# ---------------------------------------------------------------------------
# Hermes probe helpers
# ---------------------------------------------------------------------------


def _hermes_get(hermes_url: str, hermes_key: str, path: str):
    try:
        return requests.get(
            f"{hermes_url}{path}",
            headers={"Authorization": f"Bearer {hermes_key}"},
            timeout=15,
        )
    except Exception:
        return None


def hermes_health_ok(hermes_url: str) -> bool:
    try:
        r = requests.get(f"{hermes_url}/health", timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def hermes_models_ok(hermes_url: str, hermes_key: str) -> bool:
    r = _hermes_get(hermes_url, hermes_key, "/v1/models")
    if r is None or r.status_code != 200:
        return False
    return len(r.json().get("data", [])) > 0


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


def register_hermes_agent(
    gateway_url: str, token: str, endpoint_id: str, part_id: str,
    hermes_url: str, hermes_key: str, hermes_model: str,
) -> Dict[str, Any]:
    """Register the hermes-agent fixture via the daemon's own A2A GraphQL
    route (``/{endpoint_id}/a2a_core_graphql``, dispatched through
    ``silvaengine_daemon.gateway:dispatch_a2a_graphql``)."""
    metadata = {
        "agent_type": "hermes",
        "hermes_api_url": hermes_url,
        "hermes_api_key": hermes_key,
        "hermes_model": hermes_model,
    }
    mutation = """
        mutation RegisterHermesAgent(
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
        "agentId": HERMES_AGENT_ID,
        "agentName": "Hermes Agent",
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
# Test 1: Hermes bridge health and models
# ---------------------------------------------------------------------------


@_live_e2e
def test_01_hermes_health(ctx: Dict[str, Any]) -> None:
    assert hermes_health_ok(ctx["hermes_url"]), f"Hermes /health failed at {ctx['hermes_url']}"
    assert hermes_models_ok(ctx["hermes_url"], ctx["hermes_key"]), "Hermes /v1/models not reachable with the configured key"


# ---------------------------------------------------------------------------
# Test 2: gateway health
# ---------------------------------------------------------------------------


@_live_e2e
def test_02_gateway_health(ctx: Dict[str, Any]) -> None:
    assert gateway_health_ok(ctx["gateway_url"], ctx["token"]), (
        f"Gateway /health failed at {ctx['gateway_url']}"
    )


# ---------------------------------------------------------------------------
# Test 3: register/verify the hermes-agent fixture via the daemon
# ---------------------------------------------------------------------------


@_live_e2e
def test_03_register_agent(ctx: Dict[str, Any]) -> None:
    result = register_hermes_agent(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        ctx["hermes_url"], ctx["hermes_key"], ctx["hermes_model"],
    )
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Test 4: non-streaming message/send through the new plugin-routing path
# ---------------------------------------------------------------------------


@_live_e2e
def test_04_non_streaming_send(ctx: Dict[str, Any]) -> None:
    params = {
        "message": {"role": "user", "parts": [{"text": "Say hello in one word."}]},
        "metadata": {"operation": "message_response", "agent_uuid": HERMES_AGENT_ID},
    }
    r = send_a2a(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "message/send", params, "hermes-daemon-e2e-send-001",
    )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    body = r.json()
    assert not body.get("error"), f"JSON-RPC error: {body.get('error')}"
    text = extract_text(body.get("result", {}))
    assert not is_error_text(text), f"Response is an error, not a real reply: {text[:200]}"
    assert len(text) > 0, "Response text is empty"


# ---------------------------------------------------------------------------
# Test 5: compatibility message/send (different prompt)
# ---------------------------------------------------------------------------


@_live_e2e
def test_05_compat(ctx: Dict[str, Any]) -> None:
    params = {
        "message": {"role": "user", "parts": [{"text": "Confirm you are Hermes Agent. Reply in one sentence."}]},
        "metadata": {"operation": "message_response", "agent_uuid": HERMES_AGENT_ID},
    }
    r = send_a2a(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "message/send", params, "hermes-daemon-e2e-compat-001",
    )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    body = r.json()
    error = body.get("error")
    if error:
        assert error.get("code") != -32601, f"message/send not found: {error}"
    else:
        text = extract_text(body.get("result", {}))
        assert not is_error_text(text), f"Response is an error, not a real reply: {text[:200]}"
        assert len(text) > 0, "Compatibility response empty"


# ---------------------------------------------------------------------------
# Test 6: cancel a task
# ---------------------------------------------------------------------------


@_live_e2e
def test_06_cancel(ctx: Dict[str, Any]) -> None:
    task_id = f"hermes-daemon-cancel-{uuid.uuid4().hex[:8]}"
    r = send_a2a(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "tasks/cancel", {"id": task_id}, "hermes-daemon-e2e-cancel-001", timeout=30,
    )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    body = r.json()
    if body.get("error"):
        assert "not found" in body["error"].get("message", "").lower()


# ---------------------------------------------------------------------------
# Test 7: failure case — unknown agent + wrong Hermes key
# ---------------------------------------------------------------------------


@_live_e2e
def test_07_failure(ctx: Dict[str, Any]) -> None:
    params = {
        "message": {"role": "user", "parts": [{"text": "This should fail."}]},
        "metadata": {"operation": "message_response", "agent_uuid": "nonexistent-agent-xyz"},
    }
    r = send_a2a(
        ctx["gateway_url"], ctx["token"], ctx["endpoint_id"], ctx["part_id"],
        "message/send", params, "hermes-daemon-e2e-fail-001", timeout=60,
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

    wrong_r = _hermes_get(ctx["hermes_url"], "wrong-key-12345", "/v1/models")
    assert wrong_r is not None and wrong_r.status_code in (401, 403), (
        f"Expected 401/403 with wrong Hermes key, got {wrong_r.status_code if wrong_r else 'None'}"
    )
    ok_r = _hermes_get(ctx["hermes_url"], ctx["hermes_key"], "/v1/models")
    assert ok_r is not None and ok_r.status_code == 200, (
        f"Expected 200 with correct Hermes key, got {ok_r.status_code if ok_r else 'None'}"
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
    hermes_url = args.hermes_url or env.get("HERMES_API_URL", DEFAULT_HERMES_URL)
    hermes_key = args.hermes_key or env.get("HERMES_API_KEY", "")
    hermes_model = env.get("HERMES_MODEL", "hermes-agent")
    endpoint_id = args.endpoint_id or env.get("endpoint_id", "gpt")
    part_id = args.part_id or env.get("part_id", "nestaging")
    token = args.token or generate_token(env, gateway_url)
    return {
        "gateway_url": gateway_url,
        "hermes_url": hermes_url,
        "hermes_key": hermes_key,
        "hermes_model": hermes_model,
        "endpoint_id": endpoint_id,
        "part_id": part_id,
        "token": token,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live E2E: SilvaEngine Gateway -> silvaengine_daemon plugin "
        "routing -> a2a_protocol_plugin -> Hermes Agent bridge"
    )
    parser.add_argument("--gateway-url", default=None)
    parser.add_argument("--hermes-url", default=None)
    parser.add_argument("--hermes-key", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--endpoint-id", default=None)
    parser.add_argument("--part-id", default=None)
    args = parser.parse_args()

    print("=" * 70)
    print("silvaengine_daemon -> a2a_protocol_plugin -> Hermes Agent bridge E2E")
    print("=" * 70)

    print(f"  Routing check: a2a_jsonrpc -> {get_dispatch_ref('a2a_jsonrpc')}")

    ctx = build_context(args)
    print(f"  Gateway:  {ctx['gateway_url']}")
    print(f"  Hermes:   {ctx['hermes_url']}")
    print(f"  Endpoint: {ctx['endpoint_id']} / {ctx['part_id']}")

    tests = [
        ("E2E-001", "Hermes bridge health & models", lambda: test_01_hermes_health(ctx)),
        ("E2E-002", "Gateway health", lambda: test_02_gateway_health(ctx)),
        ("E2E-003", "Register hermes-agent", lambda: test_03_register_agent(ctx)),
        ("E2E-004", "Non-streaming message/send", lambda: test_04_non_streaming_send(ctx)),
        ("E2E-005", "Compatibility message/send", lambda: test_05_compat(ctx)),
        ("E2E-006", "Cancel task", lambda: test_06_cancel(ctx)),
        ("E2E-007", "Failure: unknown agent + wrong key", lambda: test_07_failure(ctx)),
    ]
    for tid, tname, fn in tests:
        run_test(tid, tname, fn)
        time.sleep(1)

    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    print(f"\n{'=' * 70}")
    print(f"Results: {passed} passed, {failed} failed, {len(RESULTS)} total")
    print(f"{'=' * 70}")

    results_path = TESTS_DIR.parent / "docs" / "test_results" / "hermes_gateway_e2e_results.json"
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
