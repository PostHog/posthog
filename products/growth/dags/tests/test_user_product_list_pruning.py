from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import ANY, MagicMock, patch

from django.utils import timezone

from dagster import build_op_context

from posthog.models import Organization, Team, User
from posthog.models.file_system.user_product_list import UserProductList

from products.growth.dags import user_product_list_pruning
from products.growth.dags.user_product_list import get_valid_product_paths
from products.growth.dags.user_product_list_pruning import (
    SKIP_EMPTY_SIDEBAR,
    SKIP_NO_USAGE,
    SKIP_RECENT_USER,
    UNMAPPED_PRODUCT_PATHS,
    URL_KEY_TO_PRODUCT_PATH,
    ProductListRow,
    first_segment_whitelist,
    parse_usage_csv,
    prune_unused_user_products,
    select_rows_to_prune,
)

CUTOFF = datetime(2026, 6, 1, tzinfo=UTC)
OLD = CUTOFF - timedelta(days=30)
RECENT = CUTOFF + timedelta(days=10)

HEADER = "distinct_id,browsed_team_id,url_key,last_seen"
SEEN = (CUTOFF + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")


def _row(id: str, product_path: str, *, enabled: bool = True, created_at: datetime = OLD) -> ProductListRow:
    return ProductListRow(id=id, product_path=product_path, enabled=enabled, created_at=created_at)


class TestSelectRowsToPrune:
    @pytest.mark.parametrize(
        "row,used_paths,expected_ids",
        [
            # Unused, old, enabled, mappable -> pruned
            (_row("a", "Surveys"), {"Product analytics"}, ["a"]),
            # Used in the window -> kept
            (_row("a", "Surveys"), {"Surveys", "Product analytics"}, []),
            # Row newer than the cutoff hasn't had a chance to be used -> kept
            (_row("a", "Surveys", created_at=RECENT), {"Product analytics"}, []),
            # Disabled rows are already out of the sidebar and record intent -> kept
            (_row("a", "Surveys", enabled=False), {"Product analytics"}, []),
            # Unmappable path (not a current product) -> kept, we can't measure it
            (_row("a", "Retired product"), {"Product analytics"}, []),
        ],
    )
    def test_row_level_rules(self, row: ProductListRow, used_paths: set[str], expected_ids: list[str]):
        # A second, used row keeps the never-empty guard out of these cases.
        rows = [row, _row("used", "Product analytics")]
        decision = select_rows_to_prune(rows, user_date_joined=OLD, used_paths=used_paths, cutoff=CUTOFF)
        assert decision.skip_reason is None
        assert [pruned.id for pruned in decision.rows] == expected_ids

    @pytest.mark.parametrize(
        "date_joined,used_paths,expected_reason",
        [
            (RECENT, {"Product analytics"}, SKIP_RECENT_USER),
            (OLD, None, SKIP_NO_USAGE),
            (OLD, set(), SKIP_NO_USAGE),
            # All enabled rows unused -> pruning would empty the sidebar
            (OLD, {"Notebooks"}, SKIP_EMPTY_SIDEBAR),
        ],
    )
    def test_user_level_skips(self, date_joined: datetime, used_paths: set[str] | None, expected_reason: str):
        rows = [_row("a", "Surveys"), _row("b", "Feature flags")]
        decision = select_rows_to_prune(rows, user_date_joined=date_joined, used_paths=used_paths, cutoff=CUTOFF)
        assert decision.skip_reason == expected_reason
        assert decision.rows == []

    def test_empty_guard_counts_disabled_rows_as_already_gone(self):
        # The one enabled row is unused; the disabled row doesn't keep the sidebar alive.
        rows = [_row("a", "Surveys"), _row("b", "Feature flags", enabled=False)]
        decision = select_rows_to_prune(rows, user_date_joined=OLD, used_paths={"Notebooks"}, cutoff=CUTOFF)
        assert decision.skip_reason == SKIP_EMPTY_SIDEBAR


class TestParseUsageCsv:
    @pytest.mark.parametrize(
        "url_key,expected_path",
        [
            ("insights", "Product analytics"),
            ("web", "Web analytics"),
            # Two-segment keys and their first-segment fallback
            ("ai-observability/playground", "Playground"),
            ("ai-observability/traces", "LLM analytics"),
            ("ai-evals/datasets", "Datasets"),
        ],
    )
    def test_maps_url_keys_to_product_paths(self, url_key: str, expected_path: str):
        parsed = parse_usage_csv([HEADER, f"u1,1,{url_key},{SEEN}"], allowed_team_ids={1}, cutoff=CUTOFF)
        assert parsed.usage == {1: {"u1": {expected_path}}}

    @pytest.mark.parametrize(
        "row",
        [
            f"u1,1,settings,{SEEN}",  # segment outside the whitelist
            f"u1,1,ai-evals/unknown,{SEEN}",  # no fallback for ai-evals
            f"u1,999,insights,{SEEN}",  # other region's team id
            f"u1,not-a-number,insights,{SEEN}",
            f",1,insights,{SEEN}",  # empty distinct_id
            "u1,1,insights,2026-04-01 00:00:00",  # last_seen before the cutoff
        ],
    )
    def test_drops_unusable_rows(self, row: str):
        assert parse_usage_csv([HEADER, row], allowed_team_ids={1}, cutoff=CUTOFF).usage == {}

    def test_stale_rows_are_counted_and_window_stats_reported(self):
        # A wider SQL window than window_days must not resurrect old usage.
        parsed = parse_usage_csv(
            [HEADER, f"u1,1,insights,{SEEN}", "u1,1,surveys,2026-04-01 00:00:00"],
            allowed_team_ids={1},
            cutoff=CUTOFF,
        )
        assert parsed.usage == {1: {"u1": {"Product analytics"}}}
        assert parsed.stale_rows_dropped == 1
        assert parsed.oldest_last_seen == datetime(2026, 6, 6, tzinfo=UTC)

    def test_unparseable_last_seen_keeps_the_row(self):
        # Usage we can't date must count as usage (it can only prevent deletions).
        parsed = parse_usage_csv([HEADER, "u1,1,insights,not-a-date"], allowed_team_ids={1}, cutoff=CUTOFF)
        assert parsed.usage == {1: {"u1": {"Product analytics"}}}

    def test_normalizes_export_header_cosmetics(self):
        # A Metabase-style export (UTF-8 BOM, spaces after commas) must not abort the run.
        bom_header = "﻿distinct_id, browsed_team_id, url_key, last_seen"
        parsed = parse_usage_csv([bom_header, f"u1,1,insights,{SEEN}"], allowed_team_ids={1}, cutoff=CUTOFF)
        assert parsed.usage == {1: {"u1": {"Product analytics"}}}

    def test_rejects_csv_with_wrong_columns(self):
        with pytest.raises(ValueError):
            parse_usage_csv(["distinct_id,team,segment", "u1,1,insights"], allowed_team_ids={1}, cutoff=CUTOFF)


class TestIterCsvLines:
    def test_reads_and_decodes_lines_from_s3(self):
        # bucket/key extraction and byte decoding are the whole S3 read path; a
        # wrong split would make the job read the wrong object (or none).
        body = MagicMock()
        body.iter_lines.return_value = [HEADER.encode(), f"u1,1,insights,{SEEN}".encode()]
        s3_client = MagicMock()
        s3_client.get_object.return_value = {"Body": body}

        lines = list(user_product_list_pruning._iter_csv_lines(s3_client, "s3://scratchpad/dir/usage.csv"))

        s3_client.get_object.assert_called_once_with(Bucket="scratchpad", Key="dir/usage.csv")
        assert lines == [HEADER, f"u1,1,insights,{SEEN}"]

    @pytest.mark.parametrize("bad_path", ["https://example.com/usage.csv", "s3://bucket-only", "s3:///key-only"])
    def test_rejects_non_s3_paths(self, bad_path: str):
        with pytest.raises(ValueError):
            list(user_product_list_pruning._iter_csv_lines(MagicMock(), bad_path))


class TestMappingDrift:
    def test_every_product_is_classified(self):
        # A new or renamed product must be added to URL_KEY_TO_PRODUCT_PATH (so the
        # pruning job can measure it) or explicitly listed in UNMAPPED_PRODUCT_PATHS
        # (so its rows are never pruned). Otherwise the job silently misjudges it.
        product_paths = get_valid_product_paths()
        mapped = set(URL_KEY_TO_PRODUCT_PATH.values())

        assert product_paths - mapped - UNMAPPED_PRODUCT_PATHS == set()
        # A mapping entry pointing at a nonexistent product is a typo or a stale rename.
        assert mapped - product_paths == set()
        assert mapped & UNMAPPED_PRODUCT_PATHS == set()

    def test_whitelist_covers_two_segment_prefixes(self):
        # The SQL whitelist is on first segments only; both shared prefixes must be in it.
        assert {"ai-observability", "ai-evals"} <= set(first_segment_whitelist())

    def test_docstring_query_whitelist_is_current(self):
        # The module docstring carries a copy-paste-runnable query with the segment
        # whitelist inlined; it must stay in lockstep with the mapping, or the
        # operator's export silently misses a product's usage and its rows get pruned.
        module_doc = " ".join((user_product_list_pruning.__doc__ or "").split())
        expected = ", ".join(f"'{segment}'" for segment in first_segment_whitelist())
        assert expected in module_doc


@pytest.mark.django_db
class TestPruneUnusedUserProductsOp:
    def _setup_team(self) -> Team:
        org = Organization.objects.create(name="Test Org")
        return Team.objects.create(organization=org, name="Test Team")

    def _create_user_with_rows(self, team: Team, email: str, distinct_id: str | None, paths: list[str]) -> User:
        user = User.objects.create(
            email=email, distinct_id=distinct_id, date_joined=timezone.now() - timedelta(days=365)
        )
        for path in paths:
            UserProductList.objects.create(user=user, team=team, product_path=path, enabled=True)
        # created_at is auto_now_add; backdate so rows are old enough to prune.
        UserProductList.objects.filter(user=user, team=team).update(created_at=timezone.now() - timedelta(days=365))
        return user

    @staticmethod
    def _seen() -> str:
        # The op computes its cutoff from the wall clock, so usage must be recent
        # relative to the real now().
        return (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

    def test_dry_run_reports_and_live_run_deletes(self):
        team = self._setup_team()
        active = self._create_user_with_rows(team, "active@x.com", "d-active", ["Product analytics", "Surveys"])
        no_usage = self._create_user_with_rows(team, "quiet@x.com", "d-quiet", ["Surveys"])
        all_unused = self._create_user_with_rows(team, "gone@x.com", "d-gone", ["Surveys", "Feature flags"])
        # Fail closed: no distinct_id means we can't match usage, so never prune.
        no_identity = self._create_user_with_rows(team, "anon@x.com", None, ["Surveys"])

        csv_lines = [
            HEADER,
            f"d-active,{team.id},insights,{self._seen()}",
            # d-gone only used pages we don't map to any of their rows' products
            f"d-gone,{team.id},heatmaps,{self._seen()}",
        ]

        config = {"usage_csv_s3_paths": ["s3://scratchpad/usage.csv"], "window_days": 60}
        resources = {"s3": MagicMock()}
        with patch(
            "products.growth.dags.user_product_list_pruning._iter_csv_lines", return_value=iter(csv_lines)
        ) as mock_fetch:
            prune_unused_user_products(build_op_context(op_config={**config, "dry_run": True}, resources=resources))
            mock_fetch.assert_called_once_with(ANY, "s3://scratchpad/usage.csv")

        # Dry run: nothing deleted
        assert UserProductList.objects.count() == 6

        with patch(
            "products.growth.dags.user_product_list_pruning._iter_csv_lines",
            side_effect=lambda client, path: iter(csv_lines),
        ):
            prune_unused_user_products(build_op_context(op_config={**config, "dry_run": False}, resources=resources))

        # active: unused Surveys deleted, used Product analytics kept
        assert set(UserProductList.objects.filter(user=active).values_list("product_path", flat=True)) == {
            "Product analytics"
        }
        # no_usage: zero pageviews -> untouched
        assert UserProductList.objects.filter(user=no_usage).count() == 1
        # all_unused: pruning would empty the sidebar -> untouched
        assert UserProductList.objects.filter(user=all_unused).count() == 2
        # no_identity: distinct_id is NULL -> unmatchable, untouched
        assert UserProductList.objects.filter(user=no_identity).count() == 1

    def test_processes_each_file_independently(self):
        # Files partitioned by distinct_id: each user's pruning must happen in the
        # file holding their usage, and both files' prunes must land in one run.
        team = self._setup_team()
        user_a = self._create_user_with_rows(team, "a@x.com", "d-a", ["Product analytics", "Surveys"])
        user_b = self._create_user_with_rows(team, "b@x.com", "d-b", ["Session replay", "Feature flags"])

        files = {
            "s3://scratchpad/part0.csv": [HEADER, f"d-a,{team.id},insights,{self._seen()}"],
            "s3://scratchpad/part1.csv": [HEADER, f"d-b,{team.id},replay,{self._seen()}"],
        }

        with patch(
            "products.growth.dags.user_product_list_pruning._iter_csv_lines",
            side_effect=lambda client, path: iter(files[path]),
        ):
            prune_unused_user_products(
                build_op_context(
                    op_config={"usage_csv_s3_paths": list(files.keys()), "dry_run": False},
                    resources={"s3": MagicMock()},
                )
            )

        assert set(UserProductList.objects.filter(user=user_a).values_list("product_path", flat=True)) == {
            "Product analytics"
        }
        assert set(UserProductList.objects.filter(user=user_b).values_list("product_path", flat=True)) == {
            "Session replay"
        }
