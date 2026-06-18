"""Read-only API over the identity matching link tables.

The tables are written by the `identity_matching_job` Dagster job
(products/growth/dags/identity_matching.py) and only exist once that job has run, so every
query first checks table existence and degrades to an empty result set.
"""

from typing import Any

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client import sync_execute
from posthog.permissions import IsStaffUser

from products.growth.backend.constants import (
    IDENTITY_MATCHING_CANDIDATE_PAIRS_TABLE,
    IDENTITY_MATCHING_LINKS_TABLE,
    IDENTITY_MATCHING_TIERS,
)

MAX_RUNS_LISTED = 50


class IdentityMatchingLinkSerializer(serializers.Serializer):
    job_id = serializers.UUIDField(help_text="Identity matching run that produced this link.")
    model_version = serializers.CharField(
        help_text="Scoring model that produced the link, e.g. 'rules_v1' or 'logreg_v1'."
    )
    orphan_distinct_id = serializers.CharField(
        help_text="Anonymous distinct ID that the model linked to an identified person."
    )
    anchor_person_key = serializers.CharField(
        help_text="Canonical distinct ID representing the matched identified person."
    )
    score = serializers.FloatField(
        help_text="Link score: weighted rule points for 'rules_v1', a 0-1 probability for 'logreg_v1'."
    )
    margin = serializers.FloatField(help_text="Score margin over the runner-up candidate person for this orphan.")
    tier = serializers.ChoiceField(
        choices=IDENTITY_MATCHING_TIERS, help_text="Confidence tier derived from score thresholds."
    )
    computed_at = serializers.DateTimeField(help_text="When the link was computed (UTC).")
    shared_ip_days = serializers.IntegerField(help_text="Distinct (IP, day) combinations both sides were seen on.")
    shared_ips = serializers.IntegerField(help_text="Distinct IPs both sides were seen on.")
    min_ip_block_size = serializers.IntegerField(
        help_text="Device count on the least crowded shared IP-day; small values suggest a household IP."
    )
    geo_city_match = serializers.BooleanField(help_text="Both sides were seen in the same city.")
    timezone_match = serializers.BooleanField(help_text="Both sides reported the same timezone.")
    language_match = serializers.BooleanField(help_text="Both sides reported the same browser language.")
    ua_exact_match = serializers.BooleanField(help_text="A byte-identical user agent was seen on both sides.")
    orphan_is_webview = serializers.BooleanField(
        help_text="The orphan's traffic came from an in-app browser or webview."
    )
    device_type_complement = serializers.BooleanField(help_text="The sides form a mobile + desktop device pair.")
    days_overlap = serializers.IntegerField(help_text="Number of days on which the two sides shared an IP.")
    avg_path_jaccard = serializers.FloatField(
        help_text="Average overlap (0-1) of pages visited by the two sides on shared IP-days."
    )
    orphan_paid_touch = serializers.BooleanField(
        help_text="The orphan arrived via a paid click ID (gclid, li_fat_id, ...) inside the window."
    )
    anchor_paid_touch = serializers.BooleanField(
        help_text="The matched person already had a paid click ID inside the window."
    )


class IdentityMatchingLinksFilterSerializer(serializers.Serializer):
    job_id = serializers.UUIDField(
        required=False, help_text="Identity matching run to read. Defaults to the team's most recent run."
    )
    model_version = serializers.CharField(
        required=False, help_text="Only return links produced by this scoring model, e.g. 'rules_v1'."
    )
    tier = serializers.ChoiceField(
        choices=IDENTITY_MATCHING_TIERS, required=False, help_text="Only return links in this confidence tier."
    )
    min_score = serializers.FloatField(required=False, help_text="Only return links with a score at or above this.")
    search = serializers.CharField(
        required=False,
        help_text="Case-insensitive substring match on the orphan distinct ID or the matched person key.",
    )
    limit = serializers.IntegerField(
        required=False, default=100, min_value=1, max_value=500, help_text="Page size, at most 500."
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0, help_text="Pagination offset.")


# many=False stops drf-spectacular from array-wrapping the list action's envelope response.
@extend_schema_serializer(many=False)
class IdentityMatchingLinksResponseSerializer(serializers.Serializer):
    results = IdentityMatchingLinkSerializer(many=True, help_text="Links ordered by score, descending.")
    count = serializers.IntegerField(help_text="Total links matching the filters, ignoring pagination.")


class IdentityMatchingRunModelCountSerializer(serializers.Serializer):
    model_version = serializers.CharField(help_text="Scoring model, e.g. 'rules_v1' or 'logreg_v1'.")
    link_count = serializers.IntegerField(help_text="Number of links this model produced in the run.")


class IdentityMatchingRunSerializer(serializers.Serializer):
    job_id = serializers.UUIDField(help_text="Identity matching run identifier (the Dagster run ID).")
    computed_at = serializers.DateTimeField(help_text="When the run wrote its links (UTC).")
    models = IdentityMatchingRunModelCountSerializer(many=True, help_text="Link counts per scoring model in this run.")


class IdentityMatchingRunsResponseSerializer(serializers.Serializer):
    results = IdentityMatchingRunSerializer(many=True, help_text="Runs ordered by recency, most recent first.")


class IdentityMatchingLinkViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    # Staff-only while identity matching is under development.
    permission_classes = [IsStaffUser]

    def _links_table_exists(self) -> bool:
        [[exists]] = sync_execute(f"EXISTS TABLE {IDENTITY_MATCHING_LINKS_TABLE}")
        return bool(exists)

    def _latest_job_id(self) -> str | None:
        rows = sync_execute(
            f"""
            SELECT job_id
            FROM {IDENTITY_MATCHING_LINKS_TABLE}
            WHERE team_id = %(team_id)s
            ORDER BY computed_at DESC
            LIMIT 1
            """,
            {"team_id": self.team.pk},
        )
        return str(rows[0][0]) if rows else None

    @extend_schema(
        summary="List identity matching links",
        description="Scored links between anonymous distinct IDs and identified persons, with the "
        "evidence behind each link. Produced by the identity matching Dagster job; empty until that "
        "job has run for this project.",
        parameters=[IdentityMatchingLinksFilterSerializer],
        responses={200: IdentityMatchingLinksResponseSerializer},
    )
    def list(self, request: Request, **kwargs: Any) -> Response:
        filters = IdentityMatchingLinksFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        params = filters.validated_data

        if not self._links_table_exists():
            return Response({"results": [], "count": 0})

        job_id = str(params["job_id"]) if params.get("job_id") else self._latest_job_id()
        if job_id is None:
            return Response({"results": [], "count": 0})

        conditions = ["lk.team_id = %(team_id)s", "lk.job_id = %(job_id)s"]
        query_params: dict[str, Any] = {
            "team_id": self.team.pk,
            "job_id": job_id,
            "limit": params["limit"],
            "offset": params["offset"],
        }
        if params.get("model_version"):
            conditions.append("lk.model_version = %(model_version)s")
            query_params["model_version"] = params["model_version"]
        if params.get("tier"):
            conditions.append("lk.tier = %(tier)s")
            query_params["tier"] = params["tier"]
        if params.get("min_score") is not None:
            conditions.append("lk.score >= %(min_score)s")
            query_params["min_score"] = params["min_score"]
        if params.get("search"):
            conditions.append(
                "(positionCaseInsensitive(lk.orphan_distinct_id, %(search)s) > 0"
                " OR positionCaseInsensitive(lk.anchor_person_key, %(search)s) > 0)"
            )
            query_params["search"] = params["search"]
        where = " AND ".join(conditions)

        [[count]] = (  # nosemgrep: clickhouse-fstring-param-audit
            sync_execute(
                f"SELECT count() FROM {IDENTITY_MATCHING_LINKS_TABLE} AS lk WHERE {where}",
                query_params,
            )
        )
        rows = sync_execute(  # nosemgrep: clickhouse-fstring-param-audit — constant table names, WHERE built from string literals, values parameterized
            f"""
            SELECT
                lk.job_id,
                lk.model_version,
                lk.orphan_distinct_id,
                lk.anchor_person_key,
                lk.score,
                lk.margin,
                lk.tier,
                lk.computed_at,
                p.shared_ip_days,
                p.shared_ips,
                p.min_ip_block_size,
                p.geo_city_match,
                p.timezone_match,
                p.language_match,
                p.ua_exact_match,
                p.orphan_is_webview,
                p.device_type_complement,
                p.days_overlap,
                p.avg_path_jaccard,
                p.orphan_paid_touch,
                p.anchor_paid_touch
            FROM {IDENTITY_MATCHING_LINKS_TABLE} AS lk
            LEFT JOIN {IDENTITY_MATCHING_CANDIDATE_PAIRS_TABLE} AS p
                ON lk.job_id = p.job_id
                AND lk.team_id = p.team_id
                AND lk.orphan_distinct_id = p.orphan_distinct_id
                AND lk.anchor_person_key = p.anchor_person_key
            WHERE {where}
            ORDER BY lk.score DESC, lk.orphan_distinct_id, lk.model_version
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            query_params,
        )
        field_names = [
            "job_id",
            "model_version",
            "orphan_distinct_id",
            "anchor_person_key",
            "score",
            "margin",
            "tier",
            "computed_at",
            "shared_ip_days",
            "shared_ips",
            "min_ip_block_size",
            "geo_city_match",
            "timezone_match",
            "language_match",
            "ua_exact_match",
            "orphan_is_webview",
            "device_type_complement",
            "days_overlap",
            "avg_path_jaccard",
            "orphan_paid_touch",
            "anchor_paid_touch",
        ]
        results = [dict(zip(field_names, row, strict=True)) for row in rows]
        response = IdentityMatchingLinksResponseSerializer({"results": results, "count": count})
        return Response(response.data)

    @extend_schema(
        summary="List identity matching runs",
        description="Recent identity matching runs for this project with link counts per scoring "
        "model, most recent first.",
        responses={200: IdentityMatchingRunsResponseSerializer},
    )
    @action(detail=False, methods=["GET"])
    def runs(self, request: Request, **kwargs: Any) -> Response:
        if not self._links_table_exists():
            return Response({"results": []})

        rows = sync_execute(
            f"""
            SELECT job_id, max(computed_at) AS computed_at, model_version, count() AS link_count
            FROM {IDENTITY_MATCHING_LINKS_TABLE}
            WHERE team_id = %(team_id)s
            GROUP BY job_id, model_version
            ORDER BY computed_at DESC
            """,
            {"team_id": self.team.pk},
        )
        runs: dict[str, dict[str, Any]] = {}
        for job_id, computed_at, model_version, link_count in rows:
            run = runs.setdefault(str(job_id), {"job_id": job_id, "computed_at": computed_at, "models": []})
            run["computed_at"] = max(run["computed_at"], computed_at)
            run["models"].append({"model_version": model_version, "link_count": link_count})
        results = list(runs.values())[:MAX_RUNS_LISTED]
        response = IdentityMatchingRunsResponseSerializer({"results": results})
        return Response(response.data)
