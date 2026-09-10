# -*- coding: utf-8 -*-
"""Unit tests for ``silvaengine_daemon.sse.SSEManager``.

Tests cover add/remove client, broadcast, partition-scoped delivery, and stats.
Uses asyncio to drive the async SSEManager methods.
"""
from __future__ import annotations

__author__ = "bibow"

import asyncio

import pytest

from silvaengine_daemon.sse import SSEManager


@pytest.fixture
def manager() -> SSEManager:
    """Return a fresh SSEManager instance for each test."""
    return SSEManager(max_history=100, max_queue_size=10)


def run_async(coro):
    """Run an async coroutine in a test (sync) context."""
    return asyncio.get_event_loop().run_until_complete(coro) if asyncio.get_event_loop().is_running() else asyncio.run(coro)


class TestSSEManager:
    """Tests for SSEManager client lifecycle and delivery."""

    @pytest.mark.asyncio
    async def test_add_client(self, manager: SSEManager) -> None:
        """add_client returns a client_id and queue."""
        client_id, queue = await manager.add_client("user1", "ep1#p1")
        assert isinstance(client_id, int)
        assert client_id > 0
        assert hasattr(queue, "get_nowait")

    @pytest.mark.asyncio
    async def test_remove_client(self, manager: SSEManager) -> None:
        """remove_client returns True for existing clients."""
        client_id, _ = await manager.add_client("user1", "ep1#p1")
        removed = await manager.remove_client(client_id, "user1")
        assert removed is True

    @pytest.mark.asyncio
    async def test_remove_nonexistent_client(self, manager: SSEManager) -> None:
        """remove_client returns False for non-existent clients."""
        removed = await manager.remove_client(99999, "nobody")
        assert removed is False

    @pytest.mark.asyncio
    async def test_broadcast_message(self, manager: SSEManager) -> None:
        """broadcast_message delivers to all connected clients."""
        client_id1, queue1 = await manager.add_client("user1", "ep1#p1")
        client_id2, queue2 = await manager.add_client("user2", "ep1#p2")

        count = await manager.broadcast_message({"type": "test", "data": "hello"})
        assert count == 2

        msg1 = queue1.get_nowait()
        msg2 = queue2.get_nowait()
        assert msg1["data"] == "hello"
        assert msg2["data"] == "hello"

    @pytest.mark.asyncio
    async def test_broadcast_to_partition(self, manager: SSEManager) -> None:
        """broadcast_to_partition only delivers to matching partition clients."""
        _, queue1 = await manager.add_client("user1", "ep1#p1")
        _, queue2 = await manager.add_client("user2", "ep1#p2")

        count = await manager.broadcast_to_partition("ep1#p1", {"type": "test"})
        assert count == 1

        msg1 = queue1.get_nowait()
        assert msg1["type"] == "test"
        # queue2 should be empty
        assert queue2.empty()

    @pytest.mark.asyncio
    async def test_broadcast_empty_partition_to_all(self, manager: SSEManager) -> None:
        """broadcast_to_partition with empty key goes to all clients."""
        _, queue1 = await manager.add_client("user1", "ep1#p1")
        _, queue2 = await manager.add_client("user2", "ep1#p2")

        count = await manager.broadcast_to_partition("", {"type": "broadcast"})
        assert count == 2

    @pytest.mark.asyncio
    async def test_send_to_client(self, manager: SSEManager) -> None:
        """send_to_client delivers to a specific client."""
        client_id, queue = await manager.add_client("user1", "ep1#p1")
        delivered = await manager.send_to_client(client_id, {"type": "direct"})
        assert delivered is True
        msg = queue.get_nowait()
        assert msg["type"] == "direct"

    @pytest.mark.asyncio
    async def test_send_to_nonexistent_client(self, manager: SSEManager) -> None:
        """send_to_client returns False for non-existent client."""
        delivered = await manager.send_to_client(99999, {"type": "x"})
        assert delivered is False

    @pytest.mark.asyncio
    async def test_send_to_user(self, manager: SSEManager) -> None:
        """send_to_user delivers to all of a user's clients."""
        _, queue1 = await manager.add_client("user1", "ep1#p1")
        _, queue2 = await manager.add_client("user1", "ep1#p2")

        delivered = await manager.send_to_user("user1", {"type": "user-msg"})
        assert delivered is True

        msg1 = queue1.get_nowait()
        msg2 = queue2.get_nowait()
        assert msg1["type"] == "user-msg"
        assert msg2["type"] == "user-msg"

    @pytest.mark.asyncio
    async def test_send_to_user_partition_scoped(self, manager: SSEManager) -> None:
        """send_to_user with partition_key only delivers to matching clients."""
        _, queue1 = await manager.add_client("user1", "ep1#p1")
        _, queue2 = await manager.add_client("user1", "ep1#p2")

        delivered = await manager.send_to_user(
            "user1", {"type": "scoped"}, partition_key="ep1#p1"
        )
        assert delivered is True

        msg1 = queue1.get_nowait()
        assert msg1["type"] == "scoped"
        assert queue2.empty()

    @pytest.mark.asyncio
    async def test_get_stats(self, manager: SSEManager) -> None:
        """get_stats returns correct counts."""
        await manager.add_client("user1", "ep1#p1")
        await manager.add_client("user2", "ep1#p1")

        stats = await manager.get_stats()
        assert stats["total_clients"] == 2
        assert stats["total_users"] == 2
        assert "user_distribution" in stats
        assert "partition_distribution" in stats

    @pytest.mark.asyncio
    async def test_cleanup_all(self, manager: SSEManager) -> None:
        """cleanup_all clears all state."""
        await manager.add_client("user1", "ep1#p1")
        await manager.cleanup_all()
        stats = await manager.get_stats()
        assert stats["total_clients"] == 0
        assert stats["total_users"] == 0

    @pytest.mark.asyncio
    async def test_get_missed_messages(self, manager: SSEManager) -> None:
        """get_missed_messages returns messages after last_event_id."""
        await manager.add_client("user1", "ep1#p1")
        await manager.broadcast_message({"type": "msg1"})
        await manager.broadcast_message({"type": "msg2"})

        # Get messages after id=1 (should get the second message)
        missed = await manager.get_missed_messages("1")
        assert len(missed) == 1
        assert missed[0]["type"] == "msg2"

    @pytest.mark.asyncio
    async def test_get_missed_messages_empty(self, manager: SSEManager) -> None:
        """get_missed_messages returns empty for invalid last_event_id."""
        await manager.add_client("user1", "ep1#p1")
        await manager.broadcast_message({"type": "msg1"})

        missed = await manager.get_missed_messages(None)
        assert missed == []

        missed = await manager.get_missed_messages("abc")
        assert missed == []