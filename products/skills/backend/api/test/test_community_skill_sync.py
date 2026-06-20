from posthog.test.base import APIBaseTest
from unittest.mock import patch

from ...models.community_skills import CommunitySkill
from ..community_skill_sync import sync_community_skills_from_github


def _create_community_skill(
    *,
    slug: str = "web-analytics-triage",
    name: str = "Web analytics triage",
    trust_tier: str = "official",
    install_count: int = 0,
    deleted: bool = False,
) -> CommunitySkill:
    return CommunitySkill.objects.create(
        slug=slug,
        name=name,
        description="Investigate a change in web traffic.",
        body="# Triage\nDo the thing.",
        trust_tier=trust_tier,
        tags=["web-analytics"],
        install_count=install_count,
        deleted=deleted,
    )


class TestCommunitySkillSync(APIBaseTest):
    @patch("products.skills.backend.api.community_skill_sync.requests.get")
    def test_sync_upserts_and_soft_deletes_missing(self, mock_get) -> None:
        _create_community_skill(slug="stale-skill", install_count=3)

        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "version": 1,
            "skills": [
                {
                    "slug": "fresh-skill",
                    "name": "Fresh skill",
                    "description": "New one",
                    "body": "# Fresh",
                    "trust_tier": "community",
                    "source_sha": "abc123",
                    "files": [{"path": "ref.md", "content": "x"}],
                }
            ],
        }

        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 1, "skipped": 0, "removed": 1})

        fresh = CommunitySkill.objects.get(slug="fresh-skill")
        self.assertEqual(fresh.files.count(), 1)
        self.assertFalse(fresh.deleted)
        self.assertIsNotNone(fresh.published_at)

        self.assertTrue(CommunitySkill.objects.get(slug="stale-skill").deleted)

    @patch("products.skills.backend.api.community_skill_sync.requests.get")
    def test_sync_skips_unchanged_sha(self, mock_get) -> None:
        existing = _create_community_skill(slug="web-analytics-triage")
        CommunitySkill.objects.filter(pk=existing.pk).update(source_sha="same-sha")

        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "skills": [
                {
                    "slug": "web-analytics-triage",
                    "name": "Web analytics triage",
                    "description": "Investigate a change in web traffic.",
                    "source_sha": "same-sha",
                }
            ],
        }

        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 0, "skipped": 1, "removed": 0})

    @patch("products.skills.backend.api.community_skill_sync.requests.get")
    def test_sync_empty_registry_does_not_wipe_catalog(self, mock_get) -> None:
        _create_community_skill(slug="keep-me")

        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {"skills": []}

        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 0, "skipped": 0, "removed": 0})
        self.assertFalse(CommunitySkill.objects.get(slug="keep-me").deleted)
