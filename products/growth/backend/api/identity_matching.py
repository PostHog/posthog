"""Read-only API over the identity matching links.

Each run of the `identity_matching_job` Dagster job (products/growth/dags/identity_matching.py)
writes its links and candidate pairs as Parquet to a per-run S3 prefix
(`<prefix>/team_<team_id>/<job_id>/...`); nothing is persisted on the ClickHouse cluster. Every
query reads those objects back through the `s3(...)` table function and degrades to an empty
result set when the team has no objects yet (a glob matching no files returns zero rows under
`s3_throw_on_zero_files_match=0`). Cross-team isolation is enforced by the `team_<team_id>` path
segment: a job_id belonging to another team resolves to a prefix this team never wrote.
"""

from typing import Any

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models import Person
from posthog.models.person.util import get_persons_mapped_by_distinct_id
from posthog.permissions import IsStaffUser

from products.growth.backend.constants import (
    IDENTITY_MATCHING_CANDIDATE_PAIRS_DATASET,
    IDENTITY_MATCHING_CANDIDATE_PAIRS_STRUCTURE,
    IDENTITY_MATCHING_LINKS_DATASET,
    IDENTITY_MATCHING_LINKS_STRUCTURE,
    IDENTITY_MATCHING_PERSON_PROPERTY_MAP,
    IDENTITY_MATCHING_S3_UNCONFIGURED_MESSAGE,
    IDENTITY_MATCHING_TIERS,
    identity_matching_dataset_read_args,
    identity_matching_s3_unconfigured,
)

MAX_RUNS_LISTED = 50


def _person_summary(distinct_id: str, persons_by_distinct_id: dict[str, Person]) -> dict[str, Any] | None:
    """Curated, display-ready summary of the person behind a distinct ID, or None when unresolved.

    Only the properties in IDENTITY_MATCHING_PERSON_PROPERTY_MAP are surfaced (renamed to clean API
    keys), so the payload stays bounded and the reviewer sees exactly the dimensions the models score
    on. Anonymous orphans with no person profile (e.g. personless capture) resolve to None.
    """
    person = persons_by_distinct_id.get(distinct_id)
    if person is None:
        return None
    properties = person.properties or {}
    summary: dict[str, Any] = {
        "distinct_id": distinct_id,
        "first_seen": person.created_at,
        "last_seen": person.last_seen_at,
    }
    for source_key, api_key in IDENTITY_MATCHING_PERSON_PROPERTY_MAP.items():
        value = properties.get(source_key)
        summary[api_key] = str(value) if value is not None else None
    return summary


# Let a glob matching no objects return zero rows (the "no run yet" path) instead of erroring.
_S3_READ_SETTINGS = {"s3_throw_on_zero_files_match": "0"}

# All-runs glob for one team: `<prefix>/team_<team_id>/*/links/*.parquet`. links is the smallest
# dataset, so enumerating every run of a team this way is cheap.
_ALL_RUNS = "*"


class IdentityMatchingPersonSerializer(serializers.Serializer):
    """The resolved person behind one side of a link, with a curated set of properties that mirror
    the match signals (geo, device, campaign) so a reviewer can judge whether the link is plausible."""

    distinct_id = serializers.CharField(help_text="Distinct ID this person was resolved from.")
    first_seen = serializers.DateTimeField(
        allow_null=True, help_text="When this person was first seen — person created_at (UTC)."
    )
    last_seen = serializers.DateTimeField(
        allow_null=True, help_text="When this person was last seen, when tracked — person last_seen_at (UTC)."
    )
    email = serializers.CharField(allow_null=True, help_text="Person's email, when set.")
    name = serializers.CharField(allow_null=True, help_text="Person's name property, when set.")
    city = serializers.CharField(allow_null=True, help_text="GeoIP city ($geoip_city_name).")
    country = serializers.CharField(allow_null=True, help_text="GeoIP country code ($geoip_country_code).")
    browser = serializers.CharField(allow_null=True, help_text="Browser ($browser).")
    os = serializers.CharField(allow_null=True, help_text="Operating system ($os).")
    device_type = serializers.CharField(
        allow_null=True, help_text="Device type, e.g. Desktop or Mobile ($device_type)."
    )
    timezone = serializers.CharField(allow_null=True, help_text="Browser timezone ($timezone).")
    utm_source = serializers.CharField(allow_null=True, help_text="Initial campaign source ($initial_utm_source).")
    utm_medium = serializers.CharField(allow_null=True, help_text="Initial campaign medium ($initial_utm_medium).")
    utm_campaign = serializers.CharField(allow_null=True, help_text="Initial campaign name ($initial_utm_campaign).")
    referring_domain = serializers.CharField(
        allow_null=True, help_text="Initial referring domain ($initial_referring_domain)."
    )
    gclid = serializers.CharField(
        allow_null=True,
        help_text="Initial Google click ID ($initial_gclid); present when the person arrived via a paid Google ad.",
    )


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
    orphan_person = IdentityMatchingPersonSerializer(
        allow_null=True,
        help_text="Resolved person behind the anonymous distinct ID; null when no profile exists for it.",
    )
    anchor_person = IdentityMatchingPersonSerializer(
        allow_null=True,
        help_text="Resolved identified person behind the matched person key; null when no profile exists for it.",
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
    high_confidence = serializers.IntegerField(help_text="Links from this model in the 'high' tier.")
    medium_confidence = serializers.IntegerField(help_text="Links from this model in the 'medium' tier.")
    low_confidence = serializers.IntegerField(help_text="Links from this model in the 'low' tier.")


class IdentityMatchingRunSerializer(serializers.Serializer):
    job_id = serializers.UUIDField(help_text="Identity matching run identifier (the Dagster run ID).")
    computed_at = serializers.DateTimeField(help_text="When the run wrote its links (UTC).")
    models = IdentityMatchingRunModelCountSerializer(many=True, help_text="Link counts per scoring model in this run.")
    total_links = serializers.IntegerField(help_text="Total links across all models in this run.")
    unique_orphans = serializers.IntegerField(help_text="Distinct anonymous visitors that were linked.")
    paid_touches = serializers.IntegerField(
        help_text="Links where a paid ad click was recovered for an anonymous visitor."
    )
    first_link_at = serializers.DateTimeField(help_text="Earliest link computed_at in the run (UTC).")
    last_link_at = serializers.DateTimeField(help_text="Latest link computed_at in the run (UTC).")


class IdentityMatchingRunsResponseSerializer(serializers.Serializer):
    results = IdentityMatchingRunSerializer(many=True, help_text="Runs ordered by recency, most recent first.")


class IdentityMatchingErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Human-readable explanation of why the request could not be served.")


class IdentityMatchingStorageUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "identity_matching_storage_unavailable"
    default_detail = IDENTITY_MATCHING_S3_UNCONFIGURED_MESSAGE


_STORAGE_UNAVAILABLE_RESPONSE = OpenApiResponse(
    response=IdentityMatchingErrorSerializer,
    description="The identity matching scratch bucket is not configured on this deployment.",
)


class IdentityMatchingLinkViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    # Staff-only while identity matching is under development.
    permission_classes = [IsStaffUser]

    def _assert_storage_configured(self) -> None:
        """Fail with a clear 503 if the scratch bucket env is missing, rather than letting every
        s3() read hit the wrong (fallback) bucket and surface an opaque AccessDenied 500."""
        if identity_matching_s3_unconfigured():
            raise IdentityMatchingStorageUnavailable()

    def _links_read_args(self, job_id: str) -> str:
        """`s3(...)` args for one run's links objects (`job_id` is a validated UUID string)."""
        return identity_matching_dataset_read_args(
            self.team.pk, job_id, IDENTITY_MATCHING_LINKS_DATASET, IDENTITY_MATCHING_LINKS_STRUCTURE
        )

    def _candidate_pairs_read_args(self, job_id: str) -> str:
        return identity_matching_dataset_read_args(
            self.team.pk, job_id, IDENTITY_MATCHING_CANDIDATE_PAIRS_DATASET, IDENTITY_MATCHING_CANDIDATE_PAIRS_STRUCTURE
        )

    def _all_runs_links_read_args(self) -> str:
        """`s3(...)` args globbing every run's links objects for this team."""
        return identity_matching_dataset_read_args(
            self.team.pk, _ALL_RUNS, IDENTITY_MATCHING_LINKS_DATASET, IDENTITY_MATCHING_LINKS_STRUCTURE
        )

    def _all_runs_candidate_pairs_read_args(self) -> str:
        """`s3(...)` args globbing every run's candidate_pairs objects for this team."""
        return identity_matching_dataset_read_args(
            self.team.pk,
            _ALL_RUNS,
            IDENTITY_MATCHING_CANDIDATE_PAIRS_DATASET,
            IDENTITY_MATCHING_CANDIDATE_PAIRS_STRUCTURE,
        )

    def _latest_job_id(self) -> str | None:
        # argMax over an empty glob returns one row with the column's default (''); treat as no run.
        with tags_context(product=Product.GROWTH, feature=Feature.QUERY):
            result = sync_execute(  # nosemgrep: clickhouse-injection-taint,clickhouse-fstring-param-audit — only the constant s3() structure/format and a team_id-derived path are interpolated; team_id is an int from the URL, all values parameterized
                f"SELECT argMax(job_id, computed_at) FROM s3({self._all_runs_links_read_args()}) WHERE team_id = %(team_id)s",
                {"team_id": self.team.pk},
                settings=_S3_READ_SETTINGS,
                team_id=self.team.pk,
            )
        job_id = result[0][0]
        return str(job_id) if job_id else None

    @extend_schema(
        summary="List identity matching links",
        description="Scored links between anonymous distinct IDs and identified persons, with the "
        "evidence behind each link. Produced by the identity matching Dagster job; empty until that "
        "job has run for this project.",
        parameters=[IdentityMatchingLinksFilterSerializer],
        responses={200: IdentityMatchingLinksResponseSerializer, 503: _STORAGE_UNAVAILABLE_RESPONSE},
    )
    def list(self, request: Request, **kwargs: Any) -> Response:
        self._assert_storage_configured()
        filters = IdentityMatchingLinksFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        params = filters.validated_data

        job_id = str(params["job_id"]) if params.get("job_id") else self._latest_job_id()
        if job_id is None:
            return Response({"results": [], "count": 0})

        # job_id scopes the run via the S3 path; team_id stays as a defensive predicate.
        conditions = ["lk.team_id = %(team_id)s"]
        query_params: dict[str, Any] = {
            "team_id": self.team.pk,
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
        links_s3 = self._links_read_args(job_id)
        candidate_pairs_s3 = self._candidate_pairs_read_args(job_id)

        with tags_context(product=Product.GROWTH, feature=Feature.QUERY):
            count_result = sync_execute(  # nosemgrep: clickhouse-injection-taint,clickhouse-fstring-param-audit — s3 path from team_id (int) and validated job_id UUID; WHERE built from literals, values parameterized
                f"SELECT count() FROM s3({links_s3}) AS lk WHERE {where}",
                query_params,
                settings=_S3_READ_SETTINGS,
                team_id=self.team.pk,
            )
            count = count_result[0][0]
            rows = sync_execute(  # nosemgrep: clickhouse-injection-taint,clickhouse-fstring-param-audit — s3 path from team_id (int) and validated job_id UUID; WHERE built from literals, values parameterized
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
                FROM s3({links_s3}) AS lk
                LEFT JOIN s3({candidate_pairs_s3}) AS p
                    ON lk.orphan_distinct_id = p.orphan_distinct_id
                    AND lk.anchor_person_key = p.anchor_person_key
                WHERE {where}
                ORDER BY lk.score DESC, lk.orphan_distinct_id, lk.model_version
                LIMIT %(limit)s OFFSET %(offset)s
                """,
                query_params,
                settings=_S3_READ_SETTINGS,
                team_id=self.team.pk,
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

        # Resolve the real persons behind each link (one batched lookup for the whole page) so the
        # UI can show identity and the properties the models score on — letting a reviewer eyeball
        # whether a match is plausible rather than guessing from a distinct ID string.
        distinct_ids = {r["orphan_distinct_id"] for r in results} | {r["anchor_person_key"] for r in results}
        persons_by_distinct_id = (
            get_persons_mapped_by_distinct_id(self.team.pk, list(distinct_ids)) if distinct_ids else {}
        )
        for result in results:
            result["orphan_person"] = _person_summary(result["orphan_distinct_id"], persons_by_distinct_id)
            result["anchor_person"] = _person_summary(result["anchor_person_key"], persons_by_distinct_id)

        response = IdentityMatchingLinksResponseSerializer({"results": results, "count": count})
        return Response(response.data)

    @extend_schema(
        summary="List identity matching runs",
        description="Recent identity matching runs for this project with link counts, tier "
        "breakdowns, and paid attribution stats per scoring model, most recent first.",
        responses={200: IdentityMatchingRunsResponseSerializer, 503: _STORAGE_UNAVAILABLE_RESPONSE},
    )
    @action(detail=False, methods=["GET"])
    def runs(self, request: Request, **kwargs: Any) -> Response:
        self._assert_storage_configured()
        with tags_context(product=Product.GROWTH, feature=Feature.QUERY):
            links_rows = sync_execute(  # nosemgrep: clickhouse-injection-taint,clickhouse-fstring-param-audit — s3 path from team_id (int); values parameterized
                f"""
                SELECT
                    job_id,
                    max(computed_at) AS latest_computed_at,
                    min(computed_at) AS earliest_computed_at,
                    model_version,
                    count() AS link_count,
                    countIf(tier = 'high') AS high_count,
                    countIf(tier = 'medium') AS medium_count,
                    countIf(tier = 'low') AS low_count,
                    groupUniqArray(orphan_distinct_id) AS orphans
                FROM s3({self._all_runs_links_read_args()})
                WHERE team_id = %(team_id)s
                GROUP BY job_id, model_version
                ORDER BY latest_computed_at DESC
                """,
                {"team_id": self.team.pk},
                settings=_S3_READ_SETTINGS,
                team_id=self.team.pk,
            )
            # Paid touch counts come from candidate_pairs (links Parquet has no paid-touch columns).
            pairs_rows = sync_execute(  # nosemgrep: clickhouse-injection-taint,clickhouse-fstring-param-audit — s3 path from team_id (int); values parameterized
                f"""
                SELECT job_id, count(DISTINCT orphan_distinct_id) AS paid_touches
                FROM s3({self._all_runs_candidate_pairs_read_args()})
                WHERE team_id = %(team_id)s AND orphan_paid_touch = 1 AND anchor_paid_touch = 0
                GROUP BY job_id
                """,
                {"team_id": self.team.pk},
                settings=_S3_READ_SETTINGS,
                team_id=self.team.pk,
            )
        paid_touches_by_run: dict[str, int] = {str(job_id): count for job_id, count in pairs_rows}

        runs: dict[str, dict[str, Any]] = {}
        for row in links_rows:
            job_id, latest_at, earliest_at, model_version, link_count, high, medium, low, orphans = row
            run = runs.setdefault(
                str(job_id),
                {
                    "job_id": job_id,
                    "computed_at": latest_at,
                    "first_link_at": earliest_at,
                    "last_link_at": latest_at,
                    "models": [],
                    "total_links": 0,
                    "unique_orphans": 0,
                    "paid_touches": paid_touches_by_run.get(str(job_id), 0),
                },
            )
            run["computed_at"] = max(run["computed_at"], latest_at)
            run["last_link_at"] = max(run["last_link_at"], latest_at)
            run["first_link_at"] = min(run["first_link_at"], earliest_at)
            run["models"].append(
                {
                    "model_version": model_version,
                    "link_count": link_count,
                    "high_confidence": high,
                    "medium_confidence": medium,
                    "low_confidence": low,
                }
            )
            run["total_links"] += link_count
            orphan_set = run.setdefault("_orphan_set", set())
            orphan_set.update(orphans)
            run["unique_orphans"] = len(orphan_set)
        results = list(runs.values())[:MAX_RUNS_LISTED]
        response = IdentityMatchingRunsResponseSerializer({"results": results})
        return Response(response.data)
