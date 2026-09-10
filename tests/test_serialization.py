# -*- coding: utf-8 -*-
"""Unit tests for ``silvaengine_daemon.serialization``.

Tests cover ``dumps`` and ``_json_default`` with datetime, pendulum-like
objects, Pydantic-like objects, and fallback str conversion.
"""
from __future__ import annotations

__author__ = "bibow"

import json
from datetime import datetime, timezone

from silvaengine_daemon.serialization import dumps, _json_default


class TestJsonDefault:
    """Tests for _json_default."""

    def test_datetime(self) -> None:
        """datetime objects are converted to ISO format strings."""
        dt = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
        result = _json_default(dt)
        assert result == dt.isoformat()
        # Verify it round-trips through json.dumps
        assert json.loads(json.dumps(dt, default=_json_default)) == dt.isoformat()

    def test_isoformat_fallback(self) -> None:
        """Objects with isoformat() but not datetime are handled."""

        class FakeDate:
            def isoformat(self) -> str:
                return "2026-09-10"

        result = _json_default(FakeDate())
        assert result == "2026-09-10"

    def test_pendulum_like(self) -> None:
        """pendulum-like objects (subclass datetime) are handled."""

        class PendulumLike(datetime):
            pass

        dt = PendulumLike(2026, 9, 10, 12, 0, 0)
        result = _json_default(dt)
        assert "2026-09-10" in result

    def test_model_dump(self) -> None:
        """Objects with model_dump() are handled."""

        class FakeModel:
            def model_dump(self, mode: str = "python") -> dict:
                return {"key": "value"}

        result = _json_default(FakeModel())
        assert result == {"key": "value"}

    def test_dict_method(self) -> None:
        """Objects with dict() (Pydantic v1) are handled."""

        class FakeV1Model:
            def dict(self) -> dict:
                return {"v1": True}

        result = _json_default(FakeV1Model())
        assert result == {"v1": True}

    def test_fallback_str(self) -> None:
        """Unknown objects fall back to str()."""

        class Unknown:
            def __str__(self) -> str:
                return "unknown-obj"

        result = _json_default(Unknown())
        assert result == "unknown-obj"


class TestDumps:
    """Tests for dumps."""

    def test_simple_dict(self) -> None:
        """Simple dict serializes correctly."""
        result = dumps({"key": "value"})
        assert json.loads(result) == {"key": "value"}

    def test_datetime_in_dict(self) -> None:
        """datetime values in dicts are serialized."""
        dt = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
        result = dumps({"timestamp": dt})
        parsed = json.loads(result)
        assert parsed["timestamp"] == dt.isoformat()

    def test_nested_datetime(self) -> None:
        """Nested datetime values are serialized."""
        dt = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
        result = dumps({"data": {"inner": {"ts": dt}}})
        parsed = json.loads(result)
        assert parsed["data"]["inner"]["ts"] == dt.isoformat()

    def test_list_with_datetime(self) -> None:
        """datetime values in lists are serialized."""
        dt1 = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
        dt2 = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)
        result = dumps({"events": [dt1, dt2]})
        parsed = json.loads(result)
        assert parsed["events"] == [dt1.isoformat(), dt2.isoformat()]

    def test_none(self) -> None:
        """None serializes correctly."""
        result = dumps(None)
        assert result == "null"

    def test_string(self) -> None:
        """Strings serialize correctly."""
        result = dumps("hello")
        assert json.loads(result) == "hello"