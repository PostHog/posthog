import os
import csv
import tempfile
from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import CommandError, call_command

from parameterized import parameterized

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


_TAGS_FIELDS = ["tag", "type", "n_companies", "recommendation", "reason", "note"]
_INVESTORS_FIELDS = ["investor", "aliases", "notes"]
_AI_TAG_ROW = {
    "tag": "Artificial Intelligence",
    "type": "MARKET",
    "n_companies": "9",
    "recommendation": "ai_positive",
    "reason": "",
    "note": "",
}
_YC_ROW = {"investor": "Y Combinator", "aliases": "YC|Y Combinator Continuity", "notes": ""}


def _write_csv(name: str, fieldnames: list[str], rows: list[dict[str, str]]) -> str:
    path = os.path.join(tempfile.mkdtemp(), name)
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_exports(
    tags_rows: list[dict[str, str]] | None = None, investors_rows: list[dict[str, str]] | None = None
) -> tuple[str, str]:
    return (
        _write_csv("tags.csv", _TAGS_FIELDS, [_AI_TAG_ROW] if tags_rows is None else tags_rows),
        _write_csv("investors.csv", _INVESTORS_FIELDS, [_YC_ROW] if investors_rows is None else investors_rows),
    )


def _active_version() -> str | None:
    lists = load_active_lists()
    return lists.version if lists else None


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


class TestSyncIcpScoringListsCommand(BaseTest):
    def setUp(self):
        super().setUp()
        clear_lists_cache()

    def tearDown(self):
        clear_lists_cache()
        super().tearDown()

    def _sync(self, tags_path: str, investors_path: str, version: str, activate: bool = False) -> str:
        out = StringIO()
        call_command(
            "sync_icp_scoring_lists",
            "--tags-csv",
            tags_path,
            "--investors-csv",
            investors_path,
            "--list-version",
            version,
            *(["--activate"] if activate else []),
            stdout=out,
            no_color=True,
        )
        return out.getvalue()

    def _sync_error(self, tags_path: str, investors_path: str, version: str) -> str:
        with self.assertRaises(CommandError) as raised:
            self._sync(tags_path, investors_path, version)
        return str(raised.exception)

    def test_activate_run_stores_the_normalized_rows_and_moves_the_active_flag(self):
        _config(version="old", is_active=True)
        assert _active_version() == "old"
        tags_path, investors_path = _write_exports(
            tags_rows=[
                _AI_TAG_ROW,
                {
                    "tag": " AI Grant Batch 1 ",
                    "type": "ACCELERATOR",
                    "n_companies": "3",
                    "recommendation": "Software_Positive",
                    "reason": "grant",
                    "note": " keep ",
                },
                {"tag": "Plug and Play", "type": "ACCELERATOR", "recommendation": "ignore"},
                {"tag": "Some Vertical", "type": "MARKET", "recommendation": "software_negative+banana"},
                {"tag": "", "recommendation": "dq"},
            ],
            investors_rows=[
                _YC_ROW,
                {"investor": "Sequoia Capital", "aliases": "", "notes": "top"},
                {"investor": " ", "aliases": "dropped", "notes": ""},
            ],
        )

        output = self._sync(tags_path, investors_path, "2026-08-13", activate=True)

        assert output == (
            "created IcpScoringConfig 2026-08-13: 4 tag rows, 2 investors (1 with aliases) — active\n"
            "buckets: ai_positive=2, capital_quality=1, dq=0, software_negative=1, software_positive=1, "
            "quality_investors=4\n"
            "1 unrecognized recommendation token(s) dropped from every bucket: 'banana' x1\n"
        )
        config = IcpScoringConfig.objects.get(version="2026-08-13")
        assert config.tags == [
            {
                "tag": "Artificial Intelligence",
                "type": "MARKET",
                "recommendation": "ai_positive",
                "reason": "",
                "note": "",
            },
            {
                "tag": "AI Grant Batch 1",
                "type": "ACCELERATOR",
                "recommendation": "ai_positive+capital_quality+software_positive",
                "reason": "grant",
                "note": "keep",
            },
            {"tag": "Plug and Play", "type": "ACCELERATOR", "recommendation": "ignore", "reason": "", "note": ""},
            {
                "tag": "Some Vertical",
                "type": "MARKET",
                "recommendation": "software_negative+banana",
                "reason": "",
                "note": "",
            },
        ]
        assert config.quality_investors == [
            {"investor": "Y Combinator", "aliases": ["YC", "Y Combinator Continuity"], "notes": ""},
            {"investor": "Sequoia Capital", "aliases": [], "notes": "top"},
        ]
        assert config.is_active is True
        assert config.created_by is None
        assert IcpScoringConfig.objects.get(version="old").is_active is False
        assert _active_version() == "2026-08-13"

    def test_inactive_run_leaves_the_active_row_alone_and_warns_about_missing_aliases(self):
        _config(version="old", is_active=True)
        assert _active_version() == "old"
        tags_path, investors_path = _write_exports(
            investors_rows=[
                {"investor": "Y Combinator", "aliases": "", "notes": ""},
                {"investor": "Sequoia Capital", "aliases": "", "notes": ""},
            ]
        )

        output = self._sync(tags_path, investors_path, "no-aliases")

        assert output == (
            "created IcpScoringConfig no-aliases: 1 tag rows, 2 investors (0 with aliases) — "
            "inactive (activate via admin or --activate)\n"
            "buckets: ai_positive=1, capital_quality=0, dq=0, software_negative=0, software_positive=0, "
            "quality_investors=2\n"
            "no investor has any aliases — check whether the aliases column was renamed or dropped\n"
        )
        config = IcpScoringConfig.objects.get(version="no-aliases")
        assert config.is_active is False
        assert config.quality_investors == [
            {"investor": "Y Combinator", "aliases": [], "notes": ""},
            {"investor": "Sequoia Capital", "aliases": [], "notes": ""},
        ]
        assert IcpScoringConfig.objects.get(version="old").is_active is True
        assert _active_version() == "old"

    def test_rejects_a_version_that_already_exists(self):
        _config(version="dup")
        tags_path, investors_path = _write_exports()

        assert (
            self._sync_error(tags_path, investors_path, "dup")
            == "IcpScoringConfig version 'dup' already exists; pick a new version"
        )

    def test_rejects_an_export_it_cannot_read(self):
        tags_path = os.path.join(tempfile.mkdtemp(), "missing.csv")
        _, investors_path = _write_exports()

        assert (
            self._sync_error(tags_path, investors_path, "fresh")
            == f"could not read {tags_path}: [Errno 2] No such file or directory: {tags_path!r}"
        )

    @parameterized.expand(
        [
            (
                "tags_export_with_zero_rows",
                _TAGS_FIELDS,
                [],
                _INVESTORS_FIELDS,
                [_YC_ROW],
                "tags export parsed to zero rows; refusing to create an empty list version",
            ),
            (
                "investors_export_with_zero_rows",
                _TAGS_FIELDS,
                [_AI_TAG_ROW],
                _INVESTORS_FIELDS,
                [],
                "investors export parsed to zero rows; refusing to create an empty list version",
            ),
            (
                "tags_export_with_only_ignored_and_unknown_buckets",
                _TAGS_FIELDS,
                [
                    {"tag": "Plug and Play", "recommendation": "ignore"},
                    {"tag": "Some Vertical", "recommendation": "banana"},
                ],
                _INVESTORS_FIELDS,
                [_YC_ROW],
                "tags export for version 'fresh' parsed to buckets that are all empty "
                "(vocabulary drift, a wrong delimiter, or a shifted column?); refusing to create it",
            ),
            (
                "tags_export_missing_a_required_column",
                ["tag", "type"],
                [{"tag": "Artificial Intelligence", "type": "MARKET"}],
                _INVESTORS_FIELDS,
                [_YC_ROW],
                "{tags_path} is missing required columns: ['recommendation']",
            ),
            (
                "investors_export_missing_a_required_column",
                _TAGS_FIELDS,
                [_AI_TAG_ROW],
                ["name", "aliases"],
                [{"name": "Y Combinator", "aliases": ""}],
                "{investors_path} is missing required columns: ['investor']",
            ),
        ]
    )
    def test_refuses_a_bad_export_and_creates_no_row(
        self, _name, tags_fields, tags_rows, investors_fields, investors_rows, message
    ):
        tags_path = _write_csv("tags.csv", tags_fields, tags_rows)
        investors_path = _write_csv("investors.csv", investors_fields, investors_rows)

        assert self._sync_error(tags_path, investors_path, "fresh") == message.format(
            tags_path=tags_path, investors_path=investors_path
        )
        assert not IcpScoringConfig.objects.filter(version="fresh").exists()
