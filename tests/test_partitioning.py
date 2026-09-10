# -*- coding: utf-8 -*-
"""Unit tests for ``silvaengine_daemon.partitioning.apply_partition_defaults``.

Tests cover:
- endpoint_id + part_id → partition_key = 'endpoint_id#part_id'
- endpoint_id only → partition_key = endpoint_id
- existing partition_key preserved
- context backfill
"""
from __future__ import annotations

__author__ = "bibow"

from silvaengine_daemon.partitioning import apply_partition_defaults


class TestApplyPartitionDefaults:
    """Tests for apply_partition_defaults."""

    def test_endpoint_and_part_id(self) -> None:
        """endpoint_id + part_id → partition_key = 'endpoint_id#part_id'."""
        params: dict = {"endpoint_id": "ep1", "part_id": "p1"}
        apply_partition_defaults(params)
        assert params["partition_key"] == "ep1#p1"
        assert params["context"]["endpoint_id"] == "ep1"
        assert params["context"]["part_id"] == "p1"
        assert params["context"]["partition_key"] == "ep1#p1"

    def test_endpoint_only(self) -> None:
        """endpoint_id only → partition_key = endpoint_id."""
        params: dict = {"endpoint_id": "ep1"}
        apply_partition_defaults(params)
        assert params["partition_key"] == "ep1"
        assert params["context"]["endpoint_id"] == "ep1"
        assert "part_id" not in params["context"]
        assert params["context"]["partition_key"] == "ep1"

    def test_existing_partition_key_preserved(self) -> None:
        """Existing partition_key is not overwritten."""
        params: dict = {
            "endpoint_id": "ep1",
            "part_id": "p1",
            "partition_key": "custom#key",
        }
        apply_partition_defaults(params)
        assert params["partition_key"] == "custom#key"
        assert params["context"]["partition_key"] == "custom#key"

    def test_context_backfill(self) -> None:
        """context dict is created and backfilled with endpoint_id/part_id."""
        params: dict = {"endpoint_id": "ep1", "part_id": "p1"}
        assert "context" not in params
        apply_partition_defaults(params)
        assert isinstance(params["context"], dict)
        assert params["context"]["endpoint_id"] == "ep1"
        assert params["context"]["part_id"] == "p1"

    def test_context_not_overwritten(self) -> None:
        """Existing context values are not overwritten."""
        params: dict = {
            "endpoint_id": "ep1",
            "part_id": "p1",
            "context": {"endpoint_id": "existing"},
        }
        apply_partition_defaults(params)
        assert params["context"]["endpoint_id"] == "existing"
        assert params["context"]["part_id"] == "p1"

    def test_part_id_from_metadata(self) -> None:
        """part_id resolved from params['metadata']['part_id']."""
        params: dict = {
            "endpoint_id": "ep1",
            "metadata": {"part_id": "meta-part"},
        }
        apply_partition_defaults(params)
        assert params["partition_key"] == "ep1#meta-part"
        assert params["context"]["part_id"] == "meta-part"

    def test_part_id_from_setting(self) -> None:
        """part_id resolved from setting when not in params."""
        params: dict = {"endpoint_id": "ep1"}
        setting = {"part_id": "setting-part"}
        apply_partition_defaults(params, setting)
        assert params["partition_key"] == "ep1#setting-part"
        assert params["context"]["part_id"] == "setting-part"

    def test_endpoint_from_setting(self) -> None:
        """endpoint_id resolved from setting when not in params."""
        params: dict = {}
        setting = {"endpoint_id": "setting-ep", "part_id": "setting-part"}
        apply_partition_defaults(params, setting)
        assert params["partition_key"] == "setting-ep#setting-part"
        assert params["context"]["endpoint_id"] == "setting-ep"

    def test_no_endpoint_no_part(self) -> None:
        """No endpoint_id or part_id → no partition_key, context created."""
        params: dict = {}
        apply_partition_defaults(params)
        assert "partition_key" not in params
        assert params["context"] == {}