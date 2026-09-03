import os
import csv
import tempfile

from posthog.test.base import BaseTest

from django.core.management import CommandError, call_command

from products.growth.backend.enrichment.icp_lists import (
    build_curated_lists,
    clear_lists_cache,
    load_active_lists,
    parse_tags_csv_rows,
    unrecognized_recommendation_tokens,
)
from products.growth.backend.models import IcpScoringConfig


def _config(**overrides) -> IcpScoringConfig:
    kwargs = {
        "version": "lists-1",
        "tags": [
            {"tag": "Artificial Intelligence", "type": "MARKET", "recommendation": "ai_positive"},
            {"tag": "Developer Tools", "type": "MARKET", "recommendation": "software_positive"},
            {"tag": "AI Grant Batch 1", "type": "ACCELERATOR", "recommendation": "ai_positive+capital_quality"},
            {"tag": "Plug and Play", "type": "ACCELERATOR", "recommendation": "ignore"},
            "not-a-dict-row",
        ],
        "quality_investors": [
            {"investor": "Y Combinator", "aliases": ["YC"], "notes": ""},
            {"investor": "Sequoia Capital", "aliases": [], "notes": ""},
            {"investor": "", "aliases": ["dropped"], "notes": "no name, alias still counts"},
        ],
        "is_active": False,
    }
    kwargs.update(overrides)
    return IcpScoringConfig.objects.create(**kwargs)


class TestIcpLists(BaseTest):
    def setUp(self):
        super().setUp()
        clear_lists_cache()

    def tearDown(self):
        clear_lists_cache()
        super().tearDown()

    def test_build_curated_lists_buckets_normalizes_and_skips_malformed_rows(self):
        lists = build_curated_lists(_config())

        assert lists.version == "lists-1"
        assert "artificial intelligence" in lists.ai_positive
        assert "ai grant batch 1" in lists.ai_positive
        assert "ai grant batch 1" in lists.capital_quality  # "+"-joined recommendation lands in both
        assert "developer tools" in lists.software_positive
        assert "plug & play" not in lists.capital_quality  # "ignore" is not a bucket
        assert lists.quality_investors == {"y combinator", "yc", "sequoia capital", "dropped"}

    def test_load_active_lists_returns_none_without_an_active_row(self):
        _config()  # inactive
        assert load_active_lists() is None

    def test_load_active_lists_caches_until_cleared(self):
        config = _config(is_active=True)

        def active_version() -> str:
            lists = load_active_lists()
            assert lists is not None
            return lists.version

        assert active_version() == "lists-1"

        config.version = "lists-2"
        config.save()
        assert active_version() == "lists-1"  # cached
        clear_lists_cache()
        assert active_version() == "lists-2"

    def test_recommendation_tokens_are_normalized_and_strays_are_countable(self):
        # A reformatted sheet export ("AI_Positive ", "Capital_Quality") must not silently
        # empty a bucket; genuinely unknown tokens are surfaced by the counter the sync
        # command warns with.
        config = _config(
            version="messy",
            tags=[
                {"tag": "Artificial Intelligence", "recommendation": " AI_POSITIVE "},
                {"tag": "Developer Tools", "recommendation": "Software_Positive+banana"},
            ],
        )
        lists = build_curated_lists(config)
        assert "artificial intelligence" in lists.ai_positive
        assert "developer tools" in lists.software_positive

        strays = unrecognized_recommendation_tokens(config.tags)
        assert strays == {"banana": 1}

    def test_ai_grant_rows_are_upgraded_to_both_buckets_at_import(self):
        rows = parse_tags_csv_rows(
            [
                {
                    "tag": "AI Grant Batch 2",
                    "type": "ACCELERATOR",
                    "recommendation": "ai_positive",
                    "reason": "",
                    "note": "",
                }
            ]
        )
        assert rows[0]["recommendation"] == "ai_positive+capital_quality"

    def test_ai_grant_rewrite_keeps_cased_tokens_from_a_reformatted_export(self):
        # The rewrite must normalize tokens like build_curated_lists does, or a cased
        # export would silently drop buckets from the stored recommendation.
        rows = parse_tags_csv_rows(
            [
                {
                    "tag": "AI Grant Batch 1",
                    "type": "ACCELERATOR",
                    "recommendation": " Software_Positive +AI_POSITIVE",
                    "reason": "",
                    "note": "",
                }
            ]
        )
        assert rows[0]["recommendation"] == "ai_positive+capital_quality+software_positive"

    def _write_exports(self):
        tempdir = tempfile.mkdtemp()
        tags_path = os.path.join(tempdir, "tags.csv")
        investors_path = os.path.join(tempdir, "investors.csv")
        with open(tags_path, "w", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=["tag", "type", "n_companies", "recommendation", "reason", "note"]
            )
            writer.writeheader()
            writer.writerow(
                {
                    "tag": "Artificial Intelligence",
                    "type": "MARKET",
                    "n_companies": "9",
                    "recommendation": "ai_positive",
                    "reason": "",
                    "note": "",
                }
            )
        with open(investors_path, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["investor", "aliases", "notes"])
            writer.writeheader()
            writer.writerow({"investor": "Y Combinator", "aliases": "YC|Y Combinator Continuity", "notes": ""})
        return tags_path, investors_path

    def test_sync_command_creates_and_activates_a_row(self):
        tags_path, investors_path = self._write_exports()
        call_command(
            "sync_icp_scoring_lists",
            "--tags-csv",
            tags_path,
            "--investors-csv",
            investors_path,
            "--list-version",
            "2026-08-13",
            "--activate",
        )

        config = IcpScoringConfig.objects.get(version="2026-08-13")
        assert config.is_active is True
        assert config.quality_investors[0]["aliases"] == ["YC", "Y Combinator Continuity"]
        lists = load_active_lists()
        assert lists is not None and "y combinator continuity" in lists.quality_investors

    def test_sync_command_moves_the_active_flag_atomically(self):
        _config(version="old", is_active=True)
        tags_path, investors_path = self._write_exports()
        call_command(
            "sync_icp_scoring_lists",
            "--tags-csv",
            tags_path,
            "--investors-csv",
            investors_path,
            "--list-version",
            "new",
            "--activate",
        )

        assert IcpScoringConfig.objects.get(version="old").is_active is False
        assert IcpScoringConfig.objects.get(version="new").is_active is True

    def test_sync_command_rejects_duplicate_versions_and_empty_exports(self):
        _config(version="dup")
        tags_path, investors_path = self._write_exports()
        with self.assertRaises(CommandError):
            call_command(
                "sync_icp_scoring_lists",
                "--tags-csv",
                tags_path,
                "--investors-csv",
                investors_path,
                "--list-version",
                "dup",
            )

        empty_path = os.path.join(tempfile.mkdtemp(), "empty.csv")
        with open(empty_path, "w", newline="") as handle:
            csv.DictWriter(handle, fieldnames=["tag", "recommendation"]).writeheader()
        with self.assertRaises(CommandError):
            call_command(
                "sync_icp_scoring_lists",
                "--tags-csv",
                empty_path,
                "--investors-csv",
                investors_path,
                "--list-version",
                "fresh",
            )

    def test_sync_command_refuses_a_row_that_would_produce_only_empty_buckets(self):
        tempdir = tempfile.mkdtemp()
        tags_path = os.path.join(tempdir, "tags.csv")
        with open(tags_path, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["tag", "recommendation"])
            writer.writeheader()
            writer.writerow({"tag": "Plug and Play", "recommendation": "ignore"})
            writer.writerow({"tag": "Some Vertical", "recommendation": "banana"})
        _, investors_path = self._write_exports()

        with self.assertRaises(CommandError):
            call_command(
                "sync_icp_scoring_lists",
                "--tags-csv",
                tags_path,
                "--investors-csv",
                investors_path,
                "--list-version",
                "empty-buckets",
            )
        assert not IcpScoringConfig.objects.filter(version="empty-buckets").exists()

    def test_sync_command_warns_but_succeeds_when_no_investor_has_aliases(self):
        tags_path, _ = self._write_exports()
        tempdir = tempfile.mkdtemp()
        investors_path = os.path.join(tempdir, "investors.csv")
        with open(investors_path, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["investor", "aliases", "notes"])
            writer.writeheader()
            writer.writerow({"investor": "Y Combinator", "aliases": "", "notes": ""})
            writer.writerow({"investor": "Sequoia Capital", "aliases": "", "notes": ""})

        call_command(
            "sync_icp_scoring_lists",
            "--tags-csv",
            tags_path,
            "--investors-csv",
            investors_path,
            "--list-version",
            "no-aliases",
        )

        assert IcpScoringConfig.objects.filter(version="no-aliases").exists()
