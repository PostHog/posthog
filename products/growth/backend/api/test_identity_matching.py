import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.test.persons import create_person

from products.growth.backend.constants import (
    IDENTITY_MATCHING_CANDIDATE_PAIRS_DATASET,
    IDENTITY_MATCHING_CANDIDATE_PAIRS_STRUCTURE,
    IDENTITY_MATCHING_LINKS_DATASET,
    IDENTITY_MATCHING_LINKS_STRUCTURE,
    identity_matching_s3_args,
)

OTHER_TEAM_ID = 909_090_909

RUN_A = str(uuid4())
RUN_B = str(uuid4())
RUN_OTHER_TEAM = str(uuid4())

# computed_at controls run recency (latest run wins by default, runs() orders by it).
RUN_A_COMPUTED_AT = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
RUN_B_COMPUTED_AT = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)

_S3_WRITE_SETTINGS = {"s3_truncate_on_insert": "1"}


class TestIdentityMatchingLinksAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        # S3 objects are not transactional, so a per-test prefix isolates fixtures across tests
        # (and from prod data). The object store is ephemeral, so no explicit teardown is needed.
        self._prefix_override = override_settings(IDENTITY_MATCHING_S3_PREFIX=f"identity_matching_test_{uuid4().hex}")
        self._prefix_override.enable()

    def tearDown(self) -> None:
        self._prefix_override.disable()
        super().tearDown()

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
        # Each link/pair is its own Parquet part object, matching how the job writes per-run S3
        # datasets. The pair key is deterministic so the rules and logreg links for one orphan
        # share a single candidate_pairs row (truncate-on-insert), avoiding a join fan-out.
        pair_key = hashlib.sha256(f"{orphan}|{anchor}".encode()).hexdigest()[:12]
        links_args = identity_matching_s3_args(
            team_id,
            job_id,
            f"{IDENTITY_MATCHING_LINKS_DATASET}/{model_version}_{pair_key}.parquet",
            IDENTITY_MATCHING_LINKS_STRUCTURE,
        )
        sync_execute(  # nosemgrep: clickhouse-fstring-param-audit — test fixture; s3 args from constants, all values parameterized
            f"""
            INSERT INTO FUNCTION s3({links_args})
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
            settings=_S3_WRITE_SETTINGS,
        )
        pairs_args = identity_matching_s3_args(
            team_id,
            job_id,
            f"{IDENTITY_MATCHING_CANDIDATE_PAIRS_DATASET}/{pair_key}.parquet",
            IDENTITY_MATCHING_CANDIDATE_PAIRS_STRUCTURE,
        )
        sync_execute(  # nosemgrep: clickhouse-fstring-param-audit — test fixture; s3 args from constants, all values parameterized
            f"""
            INSERT INTO FUNCTION s3({pairs_args})
            VALUES (%(job_id)s, %(team_id)s, %(orphan)s, %(anchor)s, 3, 1, 2, 1, 1, 1, 0, 0, 1, 3,
                    3600, 0.5, %(orphan_paid_touch)s, 0, 10, 20, -1)
            """,
            {
                "job_id": job_id,
                "team_id": team_id,
                "orphan": orphan,
                "anchor": anchor,
                "orphan_paid_touch": orphan_paid_touch,
            },
            settings=_S3_WRITE_SETTINGS,
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
        # No objects written for this team: both endpoints glob an empty prefix and degrade cleanly.
        response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": [], "count": 0}
        runs_response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/runs/")
        assert runs_response.status_code == status.HTTP_200_OK
        assert runs_response.json() == {"results": []}

    @parameterized.expand([("links", ""), ("runs", "runs/")])
    def test_returns_503_when_scratch_bucket_unconfigured_on_cloud(self, _name: str, suffix: str) -> None:
        # On Cloud, an unset IDENTITY_MATCHING_S3_BUCKET falls back to OBJECT_STORAGE_BUCKET; both
        # equal means the env is missing, so the endpoint should fail loudly instead of reading the
        # wrong bucket. Force equality so the assertion holds regardless of the CI environment.
        with override_settings(CLOUD_DEPLOYMENT="US", IDENTITY_MATCHING_S3_BUCKET="b", OBJECT_STORAGE_BUCKET="b"):
            response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/{suffix}")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "IDENTITY_MATCHING_S3_BUCKET" in response.json()["detail"]

    def test_runs_lists_link_counts_per_model(self) -> None:
        self._seed()
        response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/runs/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert [run["job_id"] for run in results] == [RUN_A, RUN_B]
        run_a_models = {model["model_version"]: model["link_count"] for model in results[0]["models"]}
        assert run_a_models == {"rules_v1": 2, "logreg_v1": 1}
        run_a = results[0]
        assert run_a["total_links"] == 3
        assert run_a["unique_orphans"] == 2
        assert run_a["paid_touches"] == 1  # phone-2 has orphan_paid_touch=1
        assert run_a["first_link_at"] is not None
        assert run_a["last_link_at"] is not None
        run_a_rules = {m["model_version"]: m for m in run_a["models"]}["rules_v1"]
        assert run_a_rules["high_confidence"] == 1
        assert run_a_rules["medium_confidence"] == 1
        assert run_a_rules["low_confidence"] == 0

    def test_links_are_enriched_with_resolved_persons(self) -> None:
        create_person(
            team=self.team,
            distinct_ids=["phone-1"],
            properties={
                "$geoip_city_name": "Lisbon",
                "$browser": "Mobile Safari",
                "$initial_utm_source": "google",
                "$initial_gclid": "Cj0KexampleABC",
            },
            last_seen_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        )
        create_person(
            team=self.team,
            distinct_ids=["anna@x.com"],
            properties={"email": "anna@x.com", "name": "Anna", "$geoip_city_name": "Lisbon"},
        )
        self._insert_link(self.team.pk, RUN_A, "phone-1", "anna@x.com", score=7.0, tier="high", orphan_paid_touch=1)
        # An orphan with no person profile must resolve to null, not error.
        self._insert_link(self.team.pk, RUN_A, "ghost-2", "anna@x.com", score=4.0, tier="medium")

        response = self.client.get(f"/api/projects/{self.team.pk}/identity_matching_links/")
        assert response.status_code == status.HTTP_200_OK
        by_orphan = {row["orphan_distinct_id"]: row for row in response.json()["results"]}

        # Curated properties are surfaced under clean keys ($geoip_city_name -> city, etc.).
        orphan = by_orphan["phone-1"]["orphan_person"]
        assert orphan["city"] == "Lisbon"
        assert orphan["browser"] == "Mobile Safari"
        assert orphan["utm_source"] == "google"
        assert orphan["gclid"] == "Cj0KexampleABC"
        assert orphan["email"] is None
        # Timestamps: created_at always present; last_seen_at surfaced when set.
        assert orphan["first_seen"] is not None
        assert orphan["last_seen"].startswith("2026-06-01")
        anchor = by_orphan["phone-1"]["anchor_person"]
        assert anchor["email"] == "anna@x.com"
        assert anchor["name"] == "Anna"
        assert anchor["first_seen"] is not None
        assert anchor["last_seen"] is None  # last_seen_at unset on this person

        # Unresolved orphan -> null person; its anchor still resolves.
        assert by_orphan["ghost-2"]["orphan_person"] is None
        assert by_orphan["ghost-2"]["anchor_person"]["email"] == "anna@x.com"
