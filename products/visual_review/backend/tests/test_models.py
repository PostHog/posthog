"""Tests for visual_review models."""

import uuid

import pytest

from products.visual_review.backend.models import Snapshot


@pytest.fixture
def snapshot():
    """Create a test snapshot."""
    return Snapshot(name="test-snapshot", storage_path="/test/path")


class TestSnapshot:
    """Tests for the Snapshot model."""

    def test_str_returns_name(self, snapshot):
        """Test __str__ returns the snapshot name."""
        assert str(snapshot) == "test-snapshot"

    def test_id_is_uuid(self, snapshot):
        """Test id is a UUID."""
        assert isinstance(snapshot.id, uuid.UUID)

    def test_default_storage_path_empty(self):
        """Test storage_path can be empty."""
        snap = Snapshot(name="minimal")
        assert snap.storage_path == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
