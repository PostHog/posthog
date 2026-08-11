from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import OperationalError

from parameterized import parameterized

from ...models.community_skills import CommunitySkill
from ..community_skill_sync import sync_community_skills_from_github
from ..skill_services import MAX_SKILL_BODY_BYTES


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
    @patch("products.skills.backend.api.community_skill_sync.github_request")
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

    @patch("products.skills.backend.api.community_skill_sync.github_request")
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

    @patch("products.skills.backend.api.community_skill_sync.github_request")
    def test_sync_empty_registry_does_not_wipe_catalog(self, mock_get) -> None:
        _create_community_skill(slug="keep-me")

        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {"skills": []}

        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 0, "skipped": 0, "removed": 0})
        self.assertFalse(CommunitySkill.objects.get(slug="keep-me").deleted)

    @patch("products.skills.backend.api.community_skill_sync.github_request")
    def test_sync_skips_malformed_entry_but_still_reconciles(self, mock_get) -> None:
        _create_community_skill(slug="stale-skill")

        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "skills": [
                {"slug": "fresh-skill", "name": "Fresh skill", "description": "New one", "body": "# Fresh"},
                {"slug": "bad-skill"},  # missing required name/description
            ],
        }

        # One bad entry must not abort the loop or block the soft-delete of stale-skill.
        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 1, "skipped": 1, "removed": 1})
        self.assertTrue(CommunitySkill.objects.filter(slug="fresh-skill", deleted=False).exists())
        self.assertFalse(CommunitySkill.objects.filter(slug="bad-skill").exists())
        self.assertTrue(CommunitySkill.objects.get(slug="stale-skill").deleted)

    @patch("products.skills.backend.api.community_skill_sync.github_request")
    def test_sync_does_not_wipe_catalog_when_no_valid_slugs(self, mock_get) -> None:
        _create_community_skill(slug="keep-me")

        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "skills": [{"name": "no slug here"}, {"foo": "bar"}],
        }

        # Non-empty registry that parses to zero valid slugs must not soft-delete everything.
        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 0, "skipped": 0, "removed": 0})
        self.assertFalse(CommunitySkill.objects.get(slug="keep-me").deleted)

    @patch("products.skills.backend.api.community_skill_sync.github_request")
    def test_sync_skips_oversized_entry(self, mock_get) -> None:
        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "skills": [
                {
                    "slug": "huge-skill",
                    "name": "Huge skill",
                    "description": "Too big",
                    "body": "x" * (MAX_SKILL_BODY_BYTES + 1),
                }
            ],
        }

        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 0, "skipped": 1, "removed": 0})
        self.assertFalse(CommunitySkill.objects.filter(slug="huge-skill").exists())

    @parameterized.expand(
        [
            ("overlong_name", {"name": "n" * 65}),
            ("overlong_slug", {"slug": "s" * 65}),
            ("overlong_source_sha", {"source_sha": "s" * 65}),
            ("overlong_file_path", {"files": [{"path": "p" * 501, "content": "x"}]}),
            ("overlong_content_type", {"files": [{"path": "a.md", "content": "x", "content_type": "t" * 101}]}),
            (
                "duplicate_file_paths",
                {"files": [{"path": "ref.md", "content": "a"}, {"path": "ref.md", "content": "b"}]},
            ),
            ("non_string_body", {"body": {"nested": "object"}}),
            ("non_dict_file", {"files": ["not-a-dict"]}),
            # A non-string bounded field has a len(), so a length-only check would pass it and
            # CharField would persist its repr as the catalog's visible text.
            ("non_string_name", {"name": ["Bad", "skill"]}),
            ("non_string_source_sha", {"source_sha": {"sha": "abc"}}),
            # Falsy non-strings are the sharper case: an `or ""` fallback coerces them to "" for
            # the length check while the raw value is what reaches the column, so Char/TextField
            # persists "False" / "0" / "[]" as the catalog's visible text.
            ("false_name", {"name": False}),
            ("zero_description", {"description": 0}),
            ("empty_list_source_sha", {"source_sha": []}),
            ("non_string_content_type", {"files": [{"path": "a.md", "content": "x", "content_type": ["text/md"]}]}),
            ("falsy_non_string_content_type", {"files": [{"path": "a.md", "content": "x", "content_type": 0}]}),
            ("falsy_non_string_file_content", {"files": [{"path": "a.md", "content": False}]}),
            # A falsy non-list `files` normalized to [] would count as "no files" — the upsert
            # deletes the existing files first, so a live skill would lose its whole bundle.
            ("falsy_non_list_files", {"files": {}}),
            # Blank passes the type and length checks but leaves a nameless catalog card, and a
            # blank description is refused by marketplace.packaging.validate_for_export.
            ("blank_name", {"name": "   "}),
            ("blank_description", {"description": ""}),
            # Case-only collisions break a case-insensitive filesystem, and the marketplace
            # tree-safety check drops the entire skill from the generated clone.
            (
                "case_only_duplicate_file_paths",
                {
                    "files": [
                        {"path": "references/Guide.md", "content": "a"},
                        {"path": "references/guide.md", "content": "b"},
                    ]
                },
            ),
            # `$` matches before a trailing newline, so a match-only check would let the newline
            # into the slug — the URL segment and the default installed-skill name.
            ("trailing_newline_slug", {"slug": "bad-skill\n"}),
            # Paths that would synthesize a corrupt git/export tree, rejected at ingest the same
            # way the skill create/import paths reject them.
            ("traversal_file_path", {"files": [{"path": "../secret", "content": "x"}]}),
            ("absolute_file_path", {"files": [{"path": "/etc/passwd", "content": "x"}]}),
            ("reserved_file_path", {"files": [{"path": "SKILL.md", "content": "x"}]}),
            (
                "backslash_duplicate_file_paths",
                {"files": [{"path": "ref/g.md", "content": "a"}, {"path": "ref\\g.md", "content": "b"}]},
            ),
            # Shape checks: a slug DRF can't route, or a mistyped metadata/tags/allowed_tools that
            # would 500 the list/detail render or fracture allowed-tools on export.
            ("non_routable_slug", {"slug": "triage.v2"}),
            ("scalar_metadata", {"metadata": 5}),
            ("non_list_tags", {"tags": 5}),
            ("whitespace_allowed_tool", {"allowed_tools": ["Bash Write"]}),
        ]
    )
    @patch("products.skills.backend.api.community_skill_sync.github_request")
    def test_sync_isolates_constraint_violating_entry(self, _name, bad_fields, mock_get) -> None:
        _create_community_skill(slug="stale-skill")
        bad_entry = {"slug": "bad-skill", "name": "Bad skill", "description": "Bad", "body": "# Bad", **bad_fields}

        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "skills": [
                {"slug": "fresh-skill", "name": "Fresh skill", "description": "New one", "body": "# Fresh"},
                bad_entry,
            ],
        }

        # An entry that would overflow a column, hit the unique file-path constraint, or be the
        # wrong shape (AttributeError) must be skipped without aborting the loop or blocking
        # reconciliation of the healthy entries.
        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 1, "skipped": 1, "removed": 1})
        self.assertTrue(CommunitySkill.objects.filter(slug="fresh-skill", deleted=False).exists())
        self.assertFalse(CommunitySkill.objects.filter(slug=bad_entry["slug"]).exists())
        self.assertTrue(CommunitySkill.objects.get(slug="stale-skill").deleted)

    @patch("products.skills.backend.api.community_skill_sync.github_request")
    def test_sync_does_not_wipe_catalog_when_all_slugged_entries_invalid(self, mock_get) -> None:
        _create_community_skill(slug="keep-me")

        mock_get.return_value.raise_for_status.return_value = None
        # Entry carries a slug but is otherwise malformed — it must not satisfy the reconciliation
        # safeguard on its own, or the whole catalog gets soft-deleted until a later good sync.
        mock_get.return_value.json.return_value = {"skills": [{"slug": "broken"}]}

        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 0, "skipped": 1, "removed": 0})
        self.assertFalse(CommunitySkill.objects.get(slug="keep-me").deleted)

    @patch("products.skills.backend.api.community_skill_sync.github_request")
    def test_sync_coerces_null_body_to_empty_string(self, mock_get) -> None:
        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "skills": [{"slug": "nullish", "name": "Nullish", "description": "Null body", "body": None}],
        }

        # A present-but-null body would violate the non-nullable TextField; coerce it to "" instead.
        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 1, "skipped": 0, "removed": 0})
        self.assertEqual(CommunitySkill.objects.get(slug="nullish").body, "")

    @patch("products.skills.backend.api.community_skill_sync.github_request")
    def test_sync_coerces_null_collection_fields_to_empty(self, mock_get) -> None:
        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "skills": [
                {
                    "slug": "nullish",
                    "name": "Nullish",
                    "description": "Explicit nulls",
                    "body": "# Nullish",
                    "allowed_tools": None,
                    "metadata": None,
                    "tags": None,
                }
            ],
        }

        # An explicitly-null collection makes .get return None rather than the model default,
        # which these non-nullable JSON columns reject at insert time.
        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 1, "skipped": 0, "removed": 0})
        skill = CommunitySkill.objects.get(slug="nullish")
        self.assertEqual((skill.allowed_tools, skill.metadata, skill.tags), ([], {}, []))

    @patch("products.skills.backend.api.community_skill_sync.github_request")
    def test_sync_survives_unhashable_slug(self, mock_get) -> None:
        _create_community_skill(slug="stale-skill")

        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "skills": [
                {"slug": {"nested": "object"}, "name": "Unhashable", "description": "d", "body": "# b"},
                {"slug": "fresh-skill", "name": "Fresh skill", "description": "New one", "body": "# Fresh"},
            ],
        }

        # A truthy-but-unhashable slug is tracked in a set outside the per-entry boundary, so it
        # would raise TypeError and abort the sync before later entries or reconciliation ran.
        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 1, "skipped": 0, "removed": 1})
        self.assertTrue(CommunitySkill.objects.filter(slug="fresh-skill", deleted=False).exists())
        self.assertTrue(CommunitySkill.objects.get(slug="stale-skill").deleted)

    @patch("products.skills.backend.api.community_skill_sync.github_request")
    def test_sync_lets_operational_database_errors_escape(self, mock_get) -> None:
        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "skills": [{"slug": "fresh-skill", "name": "Fresh skill", "description": "New one", "body": "# Fresh"}],
        }

        # A connection loss / failover / statement timeout is not one bad entry. Swallowing it
        # would report a successful sync (and skip reconciliation) while the catalog went stale.
        with patch(
            "products.skills.backend.api.community_skill_sync._upsert_community_skill",
            side_effect=OperationalError("server closed the connection unexpectedly"),
        ):
            with self.assertRaises(OperationalError):
                sync_community_skills_from_github()

    @patch("products.skills.backend.api.community_skill_sync.github_request")
    def test_sync_lowercases_tags(self, mock_get) -> None:
        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "skills": [
                {
                    "slug": "web-analytics-triage",
                    "name": "Web analytics triage",
                    "description": "Investigate a change in web traffic.",
                    "body": "# Triage",
                    "tags": ["Web-Analytics", "SQL"],
                }
            ],
        }

        # Tags are stored lowercased so the case-insensitive tag/search filters match reliably.
        sync_community_skills_from_github()
        self.assertEqual(CommunitySkill.objects.get(slug="web-analytics-triage").tags, ["web-analytics", "sql"])

    @patch("products.skills.backend.api.community_skill_sync.github_request")
    def test_sync_coerces_unknown_trust_tier_to_community(self, mock_get) -> None:
        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "skills": [
                {
                    "slug": "shady-skill",
                    "name": "Shady skill",
                    "description": "Claims a bogus tier",
                    "body": "# Shady",
                    "trust_tier": "definitely-official",
                }
            ],
        }

        result = sync_community_skills_from_github()
        self.assertEqual(result, {"synced": 1, "skipped": 0, "removed": 0})
        self.assertEqual(CommunitySkill.objects.get(slug="shady-skill").trust_tier, "community")
