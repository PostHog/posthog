from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute

from products.growth.backend.constants import IDENTITY_MATCHING_CANDIDATE_PAIRS_TABLE, IDENTITY_MATCHING_LINKS_TABLE
from products.growth.dags.identity_matching import CANDIDATE_PAIRS, LINKS

OTHER_TEAM_ID = 909_090_909

RUN_A = str(uuid4())
RUN_B = str(uuid4())
RUN_OTHER_TEAM = str(uuid4())

# Within the tables' 30-day TTL on computed_at; expired rows are dropped by ClickHouse.
RUN_A_COMPUTED_AT = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
RUN_B_COMPUTED_AT = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)


class TestIdentityMatchingLinksAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        sync_execute(LINKS.create_sql)
        sync_execute(CANDIDATE_PAIRS.create_sql)

    def _insert_link(
        self,
        team_id: int,
        job_id: str,
        orphan: str,
        anchor: str,
        score: float = 5.0,
        tier: str = "high",
        model_version: str = "rules_v1",
        computed_at: datetime | None = None,
        orphan_paid_touch: int = 0,
    ) -> None:
        computed_at = computed_at or RUN_A_COMPUTED_AT
        sync_execute(  # nosemgrep: clickhouse-fstring-param-audit — test fixture; constant table name, all values parameterized
            f"""
            INSERT INTO {IDENTITY_MATCHING_LINKS_TABLE}
            (job_id, team_id, model_version, orphan_distinct_id, anchor_person_key, score,
             runner_up_score, margin, tier, computed_at)
            VALUES (%(job_id)s, %(team_id)s, %(model_version)s, %(orphan)s, %(anchor)s,
                    %(score)s, 0.0, %(score)s, %(tier)s, %(computed_at)s)
            """,
            {
                "job_id": job_id,
                "team_id": team_id,
                "model_version": model_version,
                "orphan": orphan,
                "anchor": anchor,
                "score": score,
                "tier": tier,
                "computed_at": computed_at,
            },
        )
        sync_execute(  # nosemgrep: clickhouse-fstring-param-audit — test fixture; constant table name, all values parameterized
            f"""
            INSERT INTO {IDENTITY_MATCHING_CANDIDATE_PAIRS_TABLE}
            (job_id, team_id, orphan_distinct_id, anchor_person_key, shared_ip_days, shared_ips,
             min_ip_block_size, geo_city_match, timezone_match, language_match, ua_exact_match,
             orphan_is_webview, device_type_complement, days_overlap, orphan_last_to_anchor_first_s,
             avg_path_jaccard, orphan_paid_touch, anchor_paid_touch, orphan_event_count,
             anchor_event_count, label, computed_at)
            VALUES (%(job_id)s, %(team_id)s, %(orphan)s, %(anchor)s, 3, 1, 2, 1, 1, 1, 0, 0, 1, 3,
                    3600, 0.5, %(orphan_paid_touch)s, 0, 10, 20, -1, %(computed_at)s)
            """,
            {
                "job_id": job_id,
                "team_id": team_id,
                "orphan": orphan,
                "anchor": anchor,
                "orphan_paid_touch": orphan_paid_touch,
                "computed_at": computed_at,
            },
        )

    def _seed(self) -> None:
        self._insert_link(self.team.pk, RUN_A, "phone-1", "anna@x.com", score=7.0, tier="high")
        self._insert_link(self.team.pk, RUN_A, "phone-2", "bob@x.com", score=4.5, tier="medium", orphan_paid_touch=1)
        self._insert_link(
            self.team.pk, RUN_A, "phone-1", "anna@x.com", score=0.92, tier="high", model_version="logreg_v1"
        )
        # An older run for the same team: must not be returned by default.
        self._insert_link(
            self.team.pk,
            RUN_B,
            "phone-old",
            "old@x.com",
            score=3.0,
            tier="low",
            computed_at=RUN_B_COMPUTED_AT,
        )
        # Another team's rows: must never be visible.
        self._insert_link(OTHER_TEAM_ID, RUN_OTHER_TEAM, "phone-other-team", "intruder@x.com", score=9.0)

    def test_lists_latest_run_for_own_team_only(self) -> None:
        self._seed()
        response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 3
        orphans = {row["orphan_distinct_id"] for row in data["results"]}
        assert orphans == {"phone-1", "phone-2"}
        assert "phone-other-team" not in orphans
        assert "phone-old" not in orphans
        assert data["results"][0]["score"] == 7.0  # ordered by score, descending
        assert data["results"][0]["shared_ip_days"] == 3
        assert data["results"][0]["geo_city_match"] is True
        assert data["results"][0]["ua_exact_match"] is False

    def test_specific_run_selectable_via_job_id(self) -> None:
        self._seed()
        response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/", {"job_id": RUN_B})
        assert response.status_code == status.HTTP_200_OK
        assert {row["orphan_distinct_id"] for row in response.json()["results"]} == {"phone-old"}

    def test_other_team_rows_are_not_reachable_via_job_id(self) -> None:
        self._seed()
        response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/", {"job_id": RUN_OTHER_TEAM})
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": [], "count": 0}

    @parameterized.expand(
        [
            ({"model_version": "logreg_v1"}, {"phone-1"}),
            ({"tier": "medium"}, {"phone-2"}),
            ({"min_score": 5.0}, {"phone-1"}),
            ({"search": "PHONE-2"}, {"phone-2"}),
            ({"search": "anna"}, {"phone-1"}),
            ({"limit": 1}, {"phone-1"}),
        ]
    )
    def test_list_filters(self, params: dict[str, Any], expected_orphans: set[str]) -> None:
        self._seed()
        response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/", params)
        assert response.status_code == status.HTTP_200_OK
        assert {row["orphan_distinct_id"] for row in response.json()["results"]} == expected_orphans

    def test_invalid_filter_is_rejected(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/", {"tier": "huge"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_non_staff_user_is_denied(self) -> None:
        self.user.is_staff = False
        self.user.save()
        response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        runs_response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/runs/")
        assert runs_response.status_code == status.HTTP_403_FORBIDDEN

    def test_empty_when_no_runs_exist(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": [], "count": 0}

    def test_empty_when_tables_missing(self) -> None:
        sync_execute(f"DROP TABLE IF EXISTS {IDENTITY_MATCHING_LINKS_TABLE} SYNC")
        response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": [], "count": 0}
        runs_response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/runs/")
        assert runs_response.status_code == status.HTTP_200_OK
        assert runs_response.json() == {"results": []}

    def test_runs_lists_link_counts_per_model(self) -> None:
        self._seed()
        response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/runs/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert [run["job_id"] for run in results] == [RUN_A, RUN_B]
        run_a_models = {model["model_version"]: model["link_count"] for model in results[0]["models"]}
        assert run_a_models == {"rules_v1": 2, "logreg_v1": 1}
