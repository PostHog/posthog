"""Unit tests for logic/artifact_store.py — Artifact rows and their stored bytes."""

import pytest

from products.visual_review.backend.logic import artifact_store, repos
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestArtifactOperations:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

    def test_get_or_create_artifact_creates_new(self, repo):
        artifact, created = artifact_store.get_or_create_artifact(
            repo_id=repo.id,
            content_hash="abc123",
            storage_path="visual_review/abc123",
            width=100,
            height=200,
            size_bytes=5000,
        )

        assert created is True
        assert artifact.content_hash == "abc123"
        assert artifact.width == 100
        assert artifact.height == 200
        assert artifact.size_bytes == 5000

    def test_get_or_create_artifact_returns_existing(self, repo):
        artifact1, created1 = artifact_store.get_or_create_artifact(
            repo_id=repo.id,
            content_hash="abc123",
            storage_path="visual_review/abc123",
        )
        artifact2, created2 = artifact_store.get_or_create_artifact(
            repo_id=repo.id,
            content_hash="abc123",
            storage_path="visual_review/abc123",
        )

        assert created1 is True
        assert created2 is False
        assert artifact1.id == artifact2.id

    def test_get_artifact(self, repo):
        artifact_store.get_or_create_artifact(
            repo_id=repo.id,
            content_hash="xyz789",
            storage_path="visual_review/xyz789",
        )

        artifact = artifact_store.get_artifact(repo.id, "xyz789")

        assert artifact is not None
        assert artifact.content_hash == "xyz789"

    def test_get_artifact_not_found(self, repo):
        artifact = artifact_store.get_artifact(repo.id, "nonexistent")

        assert artifact is None

    def test_find_missing_hashes(self, repo):
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="exists1", storage_path="p/exists1")
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="exists2", storage_path="p/exists2")

        missing = artifact_store.find_missing_hashes(repo.id, ["exists1", "missing1", "exists2", "missing2"])

        assert set(missing) == {"missing1", "missing2"}

    def test_find_missing_hashes_all_exist(self, repo):
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="a", storage_path="p/a")
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="b", storage_path="p/b")

        missing = artifact_store.find_missing_hashes(repo.id, ["a", "b"])

        assert missing == []
