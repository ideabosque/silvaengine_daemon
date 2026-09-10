# -*- coding: utf-8 -*-
"""Async-from-sync execution helper.

Extracted from both engines' ``main.py``: ``_run_async``.

Runs an async coroutine from a synchronous context, handling both the
no-running-loop case (``asyncio.run``) and the running-loop case
(``ThreadPoolExecutor`` + ``asyncio.run`` in a separate thread).
"""
from __future__ import annotations

__author__ = "bibow"

import asyncio
import concurrent.futures
from typing import Any, Coroutine


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run an async coroutine from a sync context.

    When no event loop is running in the current thread, uses ``asyncio.run``
    directly. When a loop *is* running (e.g. inside a framework callback),
    spawns a dedicated thread with its own loop to avoid the
    "asyncio.run() cannot be called from a running event loop" error.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


# Public alias: plugin packages (e.g. a2a_protocol_plugin.main) import this
# as ``run_async`` since they are consumers outside this module, not internals.
run_async = _run_async

__all__ = ["_run_async", "run_async"]