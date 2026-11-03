import time
from datetime import datetime, timedelta
from functools import cached_property

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.database.schema.document_embeddings import HOGQL_EMBEDDING_TABLES
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.dataclasses import frozen
from posthog.models import Team

from products.error_tracking.backend.logic.auto_assignment.base import Assignee
from products.error_tracking.backend.models import ErrorTrackingIssueFingerprintV2

# The embedding tables keep three months of rows. Older fingerprints have nothing to compare against.
EMBEDDING_RETENTION = timedelta(days=90)
MAX_ASSIGNED_FINGERPRINTS = 5000
# Fingerprints, not issues: one merged issue can own many near-identical fingerprints.
MAX_NEAREST_FINGERPRINTS = 200
MAX_SIMILAR_ISSUES = 20
LOOKUP_MAX_EXECUTION_SECONDS = 10

NEAREST_ASSIGNED_FINGERPRINTS_QUERY = """
    SELECT document_id, cosineDistance({target_embedding}, embedding) AS distance
    FROM {table}
    WHERE document_type = 'fingerprint'
    AND product = 'error_tracking'
    AND rendering = {rendering}
    AND team_id = {team_id}
    AND timestamp >= {min_timestamp}
    AND timestamp < {max_timestamp}
    AND document_id IN {fingerprints}
    ORDER BY distance ASC
    LIMIT {limit}
"""


@frozen
class IssueEmbedding:
    model_name: str
    rendering: str
    vector: tuple[float, ...]


@frozen
class SimilarAssignedIssue:
    issue_id: str
    assignee: Assignee
    distance: float


@frozen
class SimilarIssueLookup:
    issues: tuple[SimilarAssignedIssue, ...]
    searched_fingerprints: int
    duration_ms: float


class IssueEvidence:
    """Facts about one new issue. Each fact loads on first use, so a processor that does not run costs nothing."""

    def __init__(self, team: Team, issue_id: str, created_at: datetime, embedding: IssueEmbedding | None) -> None:
        self.team = team
        self.issue_id = issue_id
        self.created_at = created_at
        self.embedding = embedding

    @cached_property
    def ai_processing_approved(self) -> bool:
        return self.team.organization.is_ai_data_processing_approved is True

    @cached_property
    def similar_assigned_issues(self) -> SimilarIssueLookup | None:
        if self.embedding is None:
            return None
        start = time.monotonic()
        assignees = self._assigned_fingerprints()
        nearest = self._nearest_fingerprints(self.embedding, list(assignees)) if assignees else []
        issues: dict[str, SimilarAssignedIssue] = {}
        for fingerprint, distance in nearest:
            issue_id, assignee = assignees[fingerprint]
            if issue_id not in issues:
                issues[issue_id] = SimilarAssignedIssue(issue_id=issue_id, assignee=assignee, distance=distance)
        return SimilarIssueLookup(
            issues=tuple(issues.values())[:MAX_SIMILAR_ISSUES],
            searched_fingerprints=len(assignees),
            duration_ms=(time.monotonic() - start) * 1000,
        )

    @property
    def similar_issue_lookup_ms(self) -> float | None:
        # Read the cache, not the property, so that asking for the timing never runs the lookup.
        lookup = self.__dict__.get("similar_assigned_issues")
        return lookup.duration_ms if lookup is not None else None

    def _assigned_fingerprints(self) -> dict[str, tuple[str, Assignee]]:
        # The fingerprint, its issue and the assignment must all predate this issue, so a backtest over past issues
        # sees only what was known at the time.
        rows = (
            ErrorTrackingIssueFingerprintV2.objects.filter(
                team_id=self.team.id,
                first_seen__gte=self.created_at - EMBEDDING_RETENTION,
                first_seen__lt=self.created_at,
                issue__created_at__lt=self.created_at,
                issue__assignment__created_at__lt=self.created_at,
            )
            .exclude(issue_id=self.issue_id)
            .order_by("-first_seen")
            .values_list("fingerprint", "issue_id", "issue__assignment__user_id", "issue__assignment__role_id")
        )[:MAX_ASSIGNED_FINGERPRINTS]
        fingerprints: dict[str, tuple[str, Assignee]] = {}
        for fingerprint, issue_id, user_id, role_id in rows:
            # Deleting a user or a role deletes its assignments, so one of the two is always set.
            assignee = (
                Assignee(type="user", id=str(user_id))
                if user_id is not None
                else Assignee(type="role", id=str(role_id))
            )
            fingerprints[fingerprint] = (str(issue_id), assignee)
        return fingerprints

    def _nearest_fingerprints(self, embedding: IssueEmbedding, fingerprints: list[str]) -> list[tuple[str, float]]:
        table = HOGQL_EMBEDDING_TABLES.get(embedding.model_name)
        if table is None:
            raise ValueError(f"Invalid embedding model: {embedding.model_name}")
        query = parse_select(
            NEAREST_ASSIGNED_FINGERPRINTS_QUERY,
            placeholders={
                "table": ast.Field(chain=[table.to_printed_hogql()]),
                "target_embedding": ast.Constant(value=list(embedding.vector)),
                "rendering": ast.Constant(value=embedding.rendering),
                "team_id": ast.Constant(value=self.team.id),
                "min_timestamp": ast.Constant(value=self.created_at - EMBEDDING_RETENTION),
                "max_timestamp": ast.Constant(value=self.created_at),
                "fingerprints": ast.Constant(value=fingerprints),
                "limit": ast.Constant(value=MAX_NEAREST_FINGERPRINTS),
            },
        )
        response = execute_hogql_query(
            query=query,
            team=self.team,
            query_type="ErrorTrackingAutoAssignmentSimilarIssues",
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.ERROR_TRACKING,
            settings=HogQLGlobalSettings(max_execution_time=LOOKUP_MAX_EXECUTION_SECONDS),
        )
        return [(str(row[0]), float(row[1])) for row in response.results]
