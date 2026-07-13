import time
from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction

import structlog
from django_deprecate_fields import deprecate_field
from rest_framework.exceptions import ValidationError

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import (
    KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT,
)
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.models.integration import Integration
from posthog.models.utils import UUIDModel, UUIDTModel
from posthog.storage import object_storage

from products.error_tracking.backend.sql import (
    INSERT_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
    INSERT_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES,
)

logger = structlog.get_logger(__name__)


class ErrorTrackingIssueManager(models.Manager):
    def with_first_seen(self):
        return self.annotate(first_seen=models.Min("fingerprints__first_seen"))


class ErrorTrackingIssueMergeResult(StrEnum):
    # The merge completed and moved source fingerprints onto the target issue.
    MERGED = "merged"
    # The request only referenced the target issue, duplicate source IDs, or no source IDs.
    NO_SOURCE_ISSUES = "no_source_issues"
    # The target or at least one source issue disappeared before row locks were acquired.
    STALE_ISSUES = "stale_issues"
    # A guarded fingerprint no longer belongs to the issue observed before the merge transaction.
    STALE_FINGERPRINTS = "stale_fingerprints"


class ErrorTrackingIssue(UUIDTModel):
    class Status(models.TextChoices):
        ARCHIVED = "archived", "Archived"
        ACTIVE = "active", "Active"
        RESOLVED = "resolved", "Resolved"
        PENDING_RELEASE = "pending_release", "Pending release"
        SUPPRESSED = "suppressed", "Suppressed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.TextField(choices=Status, default=Status.ACTIVE, null=False)
    name = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    objects = ErrorTrackingIssueManager()

    class Meta:
        db_table = "posthog_errortrackingissue"

    def merge(
        self, issue_ids: Sequence[str | UUID], expected_fingerprint_issue_ids: dict[str, UUID] | None = None
    ) -> ErrorTrackingIssueMergeResult:
        team_id = self.team_id
        target_issue_id = self.id
        source_issue_ids = _normalize_source_issue_ids(issue_ids=issue_ids, target_issue_id=target_issue_id)
        if not source_issue_ids:
            return ErrorTrackingIssueMergeResult.NO_SOURCE_ISSUES

        with transaction.atomic():
            existing_source_issue_ids = _lock_merge_issues(
                team_id=team_id, target_issue_id=target_issue_id, source_issue_ids=source_issue_ids
            )
            if not existing_source_issue_ids:
                return ErrorTrackingIssueMergeResult.STALE_ISSUES
            if expected_fingerprint_issue_ids is not None and not _lock_expected_fingerprint_issue_ids(
                team_id=team_id, expected_fingerprint_issue_ids=expected_fingerprint_issue_ids
            ):
                return ErrorTrackingIssueMergeResult.STALE_FINGERPRINTS

            locked_source_fingerprints = list(
                ErrorTrackingIssueFingerprintV2.objects.select_for_update()
                .filter(team_id=team_id, issue_id__in=existing_source_issue_ids)
                .order_by("fingerprint", "id")
            )

            overrides = update_error_tracking_issue_fingerprints(
                team_id=team_id,
                issue_id=target_issue_id,
                fingerprints=[fingerprint.fingerprint for fingerprint in locked_source_fingerprints],
            )

            # Reassign spike events from merged issues before deleting them
            ErrorTrackingSpikeEvent.objects.filter(team_id=team_id, issue_id__in=existing_source_issue_ids).update(
                issue_id=target_issue_id
            )
            ErrorTrackingIssue.objects.filter(team_id=team_id, id__in=existing_source_issue_ids).delete()

            _sync_error_tracking_issue_changes_on_commit(
                team_id=team_id, issue_ids=[target_issue_id], overrides=overrides
            )
            return ErrorTrackingIssueMergeResult.MERGED

    def split(self, fingerprints: list[dict]) -> list["ErrorTrackingIssue"]:
        team_id = self.team_id
        own_fingerprints = set(
            ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, issue_id=self.id).values_list(
                "fingerprint", flat=True
            )
        )

        overrides: list[ErrorTrackingIssueFingerprintV2] = []
        new_issues: list[ErrorTrackingIssue] = []

        with transaction.atomic():
            for entry in fingerprints:
                fp = entry["fingerprint"]
                if fp not in own_fingerprints:
                    continue
                new_issue = ErrorTrackingIssue.objects.create(
                    team_id=team_id,
                    name=entry.get("name") or "Untitled issue",
                    description=entry.get("description"),
                )
                new_issues.append(new_issue)
                overrides.extend(
                    update_error_tracking_issue_fingerprints(team_id=team_id, issue_id=new_issue.id, fingerprints=[fp])
                )
            # Spike events are no longer meaningful after splitting since the issue composition changed
            ErrorTrackingSpikeEvent.objects.filter(team_id=team_id, issue_id=self.id).delete()
            issue_ids_to_sync = [self.id] + [issue.id for issue in new_issues]
            _sync_error_tracking_issue_changes_on_commit(
                team_id=team_id, issue_ids=issue_ids_to_sync, overrides=overrides
            )
        return new_issues


class ErrorTrackingExternalReference(UUIDTModel):
    issue = models.ForeignKey(
        ErrorTrackingIssue,
        on_delete=models.CASCADE,
        related_name="external_issues",
        related_query_name="external_issue",
    )
    integration = models.ForeignKey(
        Integration,
        on_delete=models.CASCADE,
    )
    # DEPRECATED: provider can be fetched through the integration model
    provider = deprecate_field(models.TextField(null=False, blank=False))
    # DEPRECATED: ids should be placed inside the external_context json field
    external_id = deprecate_field(models.TextField(null=False, blank=False))
    external_context = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_errortrackingexternalreference"


class ErrorTrackingIssueCohort(UUIDTModel):
    issue = models.ForeignKey(
        ErrorTrackingIssue,
        on_delete=models.CASCADE,
        related_name="cohorts",
    )
    cohort = models.ForeignKey(
        "cohorts.Cohort",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Create a virtual one-to-one relationship constraint we can release later if needed
        constraints = [models.UniqueConstraint(fields=["issue"], name="unique_cohort_for_issue")]
        db_table = "posthog_errortrackingissuecohort"


class ErrorTrackingIssueAssignment(UUIDTModel):
    issue = models.OneToOneField(ErrorTrackingIssue, on_delete=models.CASCADE, related_name="assignment")
    team = models.ForeignKey("posthog.Team", null=True, on_delete=models.CASCADE, db_index=False)
    user = models.ForeignKey("posthog.User", null=True, on_delete=models.CASCADE)
    # DEPRECATED: issues can only be assigned to users or roles
    user_group = deprecate_field(models.ForeignKey("posthog.UserGroup", null=True, on_delete=models.CASCADE))
    role = models.ForeignKey("ee.Role", null=True, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_errortrackingissueassignment"
        indexes = [
            models.Index(fields=["team_id"], name="posthog_et_assignment_team_idx"),
        ]


class ErrorTrackingIssueFingerprintV2(UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    issue = models.ForeignKey(ErrorTrackingIssue, on_delete=models.CASCADE, related_name="fingerprints")
    fingerprint = models.TextField(null=False, blank=False)
    # current version of the id, used to sync with ClickHouse and collapse rows correctly for overrides ClickHouse table
    version = models.BigIntegerField(blank=True, default=0)
    first_seen = models.DateTimeField(null=True, auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "fingerprint"], name="unique_fingerprint_for_team")]
        db_table = "posthog_errortrackingissuefingerprintv2"


def _normalize_source_issue_ids(*, issue_ids: Sequence[str | UUID], target_issue_id: UUID) -> list[UUID]:
    source_issue_ids: set[UUID] = set()
    for issue_id in issue_ids:
        normalized_issue_id = UUID(str(issue_id))
        if normalized_issue_id != target_issue_id:
            source_issue_ids.add(normalized_issue_id)
    return sorted(source_issue_ids, key=lambda issue_id: issue_id.hex)


def _lock_merge_issues(*, team_id: int, target_issue_id: UUID, source_issue_ids: list[UUID]) -> list[UUID]:
    locked_issue_ids = {
        issue.id
        for issue in ErrorTrackingIssue.objects.select_for_update()
        .filter(team_id=team_id, id__in=[target_issue_id, *source_issue_ids])
        .order_by("id")
    }
    if target_issue_id not in locked_issue_ids or not set(source_issue_ids).issubset(locked_issue_ids):
        return []

    return source_issue_ids


def _lock_expected_fingerprint_issue_ids(*, team_id: int, expected_fingerprint_issue_ids: dict[str, UUID]) -> bool:
    current_fingerprint_issue_ids = {
        row.fingerprint: row.issue_id
        for row in ErrorTrackingIssueFingerprintV2.objects.select_for_update()
        .filter(team_id=team_id, fingerprint__in=list(expected_fingerprint_issue_ids))
        .order_by("fingerprint", "id")
    }
    return current_fingerprint_issue_ids == expected_fingerprint_issue_ids


def _sync_error_tracking_issue_changes_on_commit(
    *, team_id: int, issue_ids: list[UUID], overrides: list[ErrorTrackingIssueFingerprintV2]
) -> None:
    def sync_fingerprint_overrides() -> None:
        update_error_tracking_issue_fingerprint_overrides(team_id=team_id, overrides=overrides)

    def sync_issues() -> None:
        sync_issues_to_clickhouse(issue_ids=issue_ids, team_id=team_id)

    transaction.on_commit(sync_fingerprint_overrides)
    transaction.on_commit(sync_issues)


class ErrorTrackingRelease(UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    # On upload, users can provide a hash of some key identifiers, e.g. "git repo, commit, branch"
    # or similar, which we guarantee to be unique. If a user doesn't provide a hash_id, we use the
    # id of the model - TODO - should this instead by a hash of the project and version?
    # Note - the "hash" here can be misleading - it's not a hash of the "contents" of the release, but
    # of some arbitrary set of identifiers. The set of symbol sets associated with a release is
    # allowed to change over time, without needing to modify this hash_id (this is to support e.g.
    # retrying uploads that failed in a bad CI job or something). It's purpose is
    # to provide clients with the ability to fetch a release object based on information they
    # have locally (like project name and version).
    hash_id = models.TextField(null=False, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)
    version = models.TextField(null=False, blank=False)
    project = models.TextField(null=False, blank=False)  # For now, we may spin this out to a dedicated model later

    # Releases can have some metadata attached to them (like id, name, version,
    # commit, whatever), which we put onto exceptions if they're
    metadata = models.JSONField(null=True, blank=False)

    class Meta:
        indexes = [
            models.Index(fields=["team_id", "hash_id"]),
        ]

        constraints = [
            models.UniqueConstraint(fields=["team_id", "hash_id"], name="unique_release_hash_id_per_team"),
        ]
        db_table = "posthog_errortrackingrelease"


class ErrorTrackingSymbolSet(UUIDTModel):
    # Derived from the symbol set reference
    ref = models.TextField(null=False, blank=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    # How we stored this symbol set, and where to look for it
    # These are null if we failed to find a symbol set for a given reference. We store a
    # row anyway, so if someone comes along later and uploads a symbol set for this reference,
    # we can know which frame resolution results below to drop.
    storage_ptr = models.TextField(null=True, blank=False)

    # If we failed to resolve this symbol set, we store the reason here, so
    # we can return the language-relevant error in the future.
    failure_reason = models.TextField(null=True, blank=True)
    content_hash = models.TextField(null=True, blank=False)

    # Symbol sets can have an associated release, if they were uploaded
    # with one
    release = models.ForeignKey(ErrorTrackingRelease, null=True, on_delete=models.CASCADE)

    # When a symbol set is loaded, last_used is set, so we can track how often
    # symbol sets are used, and cleanup ones not used for a long time
    last_used = models.DateTimeField(null=True, blank=True)

    def delete(self, *args, **kwargs):
        storage_ptr = self.storage_ptr
        with transaction.atomic():
            # We always keep resolved frames, as they're used in the UI
            self.errortrackingstackframe_set.filter(resolved=False).delete()
            super().delete(*args, **kwargs)

        # We'd rather have orphan objects in s3 than records in postgres that don't actually point
        # to anything, so we delete the rows and /then/ clean up the s3 object
        if storage_ptr:
            delete_symbol_set_contents(storage_ptr)

    class Meta:
        indexes = [
            models.Index(fields=["team_id", "ref"]),
            # Composite covers the cleanup filter's two OR branches: `last_used < cutoff`
            # (leading column) and `last_used IS NULL AND created_at < cutoff` (NULL group
            # then created_at range), so batch cleanup avoids a full PK-ordered scan.
            models.Index(fields=["last_used", "created_at"], name="et_symset_used_created_idx"),
        ]

        constraints = [
            models.UniqueConstraint(fields=["team_id", "ref"], name="unique_ref_per_team"),
        ]
        db_table = "posthog_errortrackingsymbolset"


class ErrorTrackingAssignmentRule(UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    user = models.ForeignKey("posthog.User", null=True, on_delete=models.CASCADE)
    # DEPRECATED: issues can only be assigned to users or roles
    user_group = deprecate_field(models.ForeignKey("posthog.UserGroup", null=True, on_delete=models.CASCADE))
    role = models.ForeignKey("ee.Role", null=True, on_delete=models.CASCADE)
    order_key = models.IntegerField(null=False, blank=False)
    bytecode = models.JSONField(null=False, blank=False)  # The bytecode of the rule
    filters = models.JSONField(null=False, blank=False)  # The json object describing the filter rule
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # If not null, the rule is disabled, for the reason listed
    # Structure is {"message": str, "issue": {}, properties: {}}. Everything except message is mostly for debugging purposes.
    disabled_data = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team_id"]),
        ]
        db_table = "posthog_errortrackingassignmentrule"

        # TODO - I think this is strictly necessary, but I'm not gonna enforce it right now while we're iterating
        # constraints = [
        #     models.UniqueConstraint(fields=["team_id", "order_key"], name="unique_order_key_per_team"),
        # ]


# A custom grouping rule works as follows:
# - Events are run against the filter code
# - If an event matches, the fingerprint of the event is set as "custom-rule:<rule_id>"
# - The rest of the issue processing happens as per usual, except that if the rule had an
#   associated assignment, that assignment is used, and the assignment rules are skipped.
#
# This means "custom issues" can still be merged and otherwise handled as you'd expect, just that
# the set of events that end up in them will be different from the default grouping rules.
class ErrorTrackingGroupingRule(UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    bytecode = models.JSONField(null=False, blank=False)  # The bytecode of the rule
    filters = models.JSONField(null=False, blank=False)  # The json object describing the filter rule
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # If not null, the rule is disabled, for the reason listed
    # Structure is {"message": str, properties: {}}. Everything except message is mostly for debugging purposes.
    disabled_data = models.JSONField(null=True, blank=True)
    # Grouping rules are ordered, and greedily evaluated
    order_key = models.IntegerField(null=False, blank=False)

    # We allow grouping rules to also auto-assign, and if they do, assignment rules are ignored
    # in favour of the assignment of the grouping rule. Notably this differs from assignment rules
    # in so far as we permit all of these to be null
    user = models.ForeignKey("posthog.User", null=True, on_delete=models.CASCADE)
    # DEPRECATED: issues can only be assigned to users or roles
    user_group = deprecate_field(models.ForeignKey("posthog.UserGroup", null=True, on_delete=models.CASCADE))
    role = models.ForeignKey("ee.Role", null=True, on_delete=models.CASCADE)

    # Users will probably find it convenient to be able to add a short description to grouping rules
    description = models.TextField(null=True)

    class Meta:
        indexes = [
            models.Index(fields=["team_id"]),
        ]
        db_table = "posthog_errortrackinggroupingrule"

        # TODO - I think this is strictly necessary, but I'm not gonna enforce it right now while we're iterating
        # constraints = [
        #     models.UniqueConstraint(fields=["team_id", "order_key"], name="unique_order_key_per_team"),
        # ]


class ErrorTrackingSuppressionRule(UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    filters = models.JSONField(null=False, blank=False)  # The json object describing the filter rule
    bytecode = models.JSONField(null=True, blank=True)
    disabled_data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Suppression rules are ordered, and greedily evaluated
    order_key = models.IntegerField(null=False, blank=False)
    # Fraction of matching events to suppress (1.0 = all, 0.5 = half, etc.)
    sampling_rate = models.FloatField(null=False, default=1.0)

    class Meta:
        indexes = [
            models.Index(fields=["team_id"]),
        ]
        db_table = "posthog_errortrackingsuppressionrule"

        # TODO - I think this is strictly necessary, but I'm not gonna enforce it right now while we're iterating
        # constraints = [
        #     models.UniqueConstraint(fields=["team_id", "order_key"], name="unique_order_key_per_team"),
        # ]


class ErrorTrackingBypassRule(UUIDTModel):
    # Bypass rules exempt matching exception events from rate limiting. When an incoming event
    # matches an enabled rule, Cymbal keeps it and charges no rate-limit tokens (neither the
    # per-issue nor the project bucket), recording a "bypassed" status instead of
    # "allowed"/"rate_limited". They are evaluated only inside the rate-limiting stage and never
    # affect suppression, which runs earlier.
    # db_constraint=False keeps the create lock-free on posthog_team (a hot table); team scoping
    # is enforced at the ORM layer and Cymbal reads by team_id via raw SQL.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    filters = models.JSONField(null=False, blank=False)  # The json object describing the filter rule
    bytecode = models.JSONField(null=True, blank=True)
    disabled_data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Bypass rules are ordered, and greedily evaluated
    order_key = models.IntegerField(null=False, blank=False)

    class Meta:
        indexes = [
            models.Index(fields=["team_id"]),
        ]
        db_table = "posthog_errortrackingbypassrule"


class ErrorTrackingAutoCaptureControls(UUIDTModel):
    """
    Controls for error tracking autocapture behavior.
    Defines sample rates, feature flag linkage, and URL/event-based triggers.
    Each team can have one set of controls per library (SDK).
    """

    class MatchType(models.TextChoices):
        ALL = "all"
        ANY = "any"

    class Library(models.TextChoices):
        WEB = "web"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    library = models.CharField(max_length=24, choices=Library, null=False, blank=False, default=Library.WEB)

    match_type = models.CharField(max_length=24, choices=MatchType, null=False, blank=False, default=MatchType.ALL)

    sample_rate = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=False,
        blank=False,
        default=Decimal(1),
        validators=[MinValueValidator(Decimal(0)), MaxValueValidator(Decimal(1))],
    )

    linked_feature_flag = models.JSONField(null=True, blank=True)
    event_triggers = ArrayField(models.TextField(null=True, blank=True), default=list, blank=True, null=True)
    url_triggers = ArrayField(models.JSONField(null=True, blank=True), default=list, blank=True, null=True)
    url_blocklist = ArrayField(models.JSONField(null=True, blank=True), default=list, blank=True, null=True)

    class Meta:
        db_table = "posthog_errortrackingautocapturecontrols"
        indexes = [
            models.Index(fields=["team_id"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["team", "library"], name="unique_controls_per_team_library"),
        ]


class ErrorTrackingStackFrame(UUIDTModel):
    # Produced by a raw frame
    raw_id = models.TextField(null=False, blank=False)
    # Raw frames could be resolved into multiple frames after demangling because of compilation process
    part = models.IntegerField(null=False, default=0)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    symbol_set = models.ForeignKey("ErrorTrackingSymbolSet", on_delete=models.SET_NULL, null=True)
    contents = models.JSONField(null=False, blank=False)
    resolved = models.BooleanField(null=False, blank=False)
    # The context around the frame, +/- a few lines, if we can get it
    context = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = []

        constraints = [
            models.UniqueConstraint(fields=["team_id", "raw_id", "part"], name="unique_team_id_raw_id_part"),
        ]

        db_table = "posthog_errortrackingstackframe"


# DEPRECATED: Use ErrorTrackingIssue instead
class ErrorTrackingGroup(UUIDTModel):
    class Status(models.TextChoices):
        ARCHIVED = "archived", "Archived"
        ACTIVE = "active", "Active"
        RESOLVED = "resolved", "Resolved"
        PENDING_RELEASE = "pending_release", "Pending release"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    fingerprint: ArrayField = ArrayField(models.TextField(null=False, blank=False), null=False, blank=False)
    merged_fingerprints: ArrayField = ArrayField(
        ArrayField(models.TextField(null=False, blank=False), null=False, blank=False),
        null=False,
        blank=False,
        default=list,
    )
    status = models.CharField(max_length=40, choices=Status, default=Status.ACTIVE, null=False)
    assignee = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "posthog_errortrackinggroup"


# DEPRECATED: Use ErrorTrackingIssueFingerprintV2 instead
class ErrorTrackingIssueFingerprint(models.Model):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_index=False)
    issue = models.ForeignKey(ErrorTrackingGroup, on_delete=models.CASCADE)
    fingerprint = models.TextField(null=False, blank=False)
    # current version of the id, used to sync with ClickHouse and collapse rows correctly for overrides ClickHouse table
    version = models.BigIntegerField(blank=True, default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "fingerprint"], name="unique fingerprint for team")]
        db_table = "posthog_errortrackingissuefingerprint"


def resolve_fingerprints_for_issues(team_id: int, issue_ids: list[str]) -> list[str]:
    return list(
        ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, issue_id__in=issue_ids).values_list(
            "fingerprint", flat=True
        )
    )


def update_error_tracking_issue_fingerprints(
    team_id: int, issue_id: str | UUID, fingerprints: list[str]
) -> list[ErrorTrackingIssueFingerprintV2]:
    if not fingerprints:
        return []

    return list(
        # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (parameterized via params list)
        ErrorTrackingIssueFingerprintV2.objects.raw(
            """
                UPDATE posthog_errortrackingissuefingerprintv2
                SET version = version + 1, issue_id = %s
                WHERE team_id = %s AND fingerprint = ANY(%s)
                RETURNING fingerprint, version, issue_id, id
            """,
            [issue_id, team_id, fingerprints],
        )
    )


def update_error_tracking_issue_fingerprint_overrides(
    team_id: int, overrides: list[ErrorTrackingIssueFingerprintV2]
) -> None:
    for override in overrides:
        override_error_tracking_issue_fingerprint(
            team_id=team_id, fingerprint=override.fingerprint, issue_id=override.issue_id, version=override.version
        )


def override_error_tracking_issue_fingerprint(
    team_id: int,
    fingerprint: str,
    issue_id: UUID,
    version=0,
    is_deleted: bool = False,
) -> None:
    p = ClickhouseProducer()
    p.produce(
        topic=KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT,
        sql=INSERT_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES,
        data={
            "team_id": team_id,
            "fingerprint": fingerprint,
            "issue_id": str(issue_id),
            "version": version,
            "is_deleted": int(is_deleted),
        },
    )


DEPRECATED_CLICKHOUSE_STATUSES = frozenset(
    {ErrorTrackingIssue.Status.ARCHIVED, ErrorTrackingIssue.Status.PENDING_RELEASE}
)


def _clickhouse_status(issue_status: str) -> str:
    if issue_status in DEPRECATED_CLICKHOUSE_STATUSES:
        return ErrorTrackingIssue.Status.RESOLVED
    return issue_status


def sync_issues_to_clickhouse(*, issue_ids: list, team_id: int) -> None:
    if not issue_ids:
        return

    issues = {
        i.id: i
        for i in ErrorTrackingIssue.objects.filter(id__in=issue_ids, team_id=team_id).select_related("assignment")
    }
    fingerprints = ErrorTrackingIssueFingerprintV2.objects.filter(issue_id__in=issue_ids, team_id=team_id)

    producer = ClickhouseProducer()
    version = int(
        time.time() * 1000
    )  # ReplacingMergeTree version — match rust/cymbal FingerprintIssueState::new (Utc::now().timestamp_millis())

    for fp in fingerprints:
        issue = issues.get(fp.issue_id)
        if issue is None:
            continue

        assignment = getattr(issue, "assignment", None)
        assigned_user_id: int | None = None
        assigned_role_id: str | None = None
        if assignment is not None:
            if assignment.user_id:
                assigned_user_id = assignment.user_id
            elif assignment.role_id:
                assigned_role_id = str(assignment.role_id)

        first_seen_raw = fp.first_seen or issue.created_at
        first_seen = format_clickhouse_timestamp(first_seen_raw) if first_seen_raw else None
        producer.produce(
            sql=INSERT_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
            topic=KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
            data={
                "fingerprint": fp.fingerprint,
                "issue_id": str(issue.id),
                "team_id": team_id,
                "issue_name": issue.name,
                "issue_description": issue.description,
                "issue_status": _clickhouse_status(issue.status),
                "assigned_user_id": assigned_user_id,
                "assigned_role_id": assigned_role_id,
                "first_seen": first_seen,
                "is_deleted": 0,
                "version": version,
            },
        )


def delete_symbol_set_contents(upload_path: str) -> None:
    if settings.OBJECT_STORAGE_ENABLED:
        object_storage.delete(file_name=upload_path)
    else:
        raise ValidationError(
            code="object_storage_required",
            detail="Object storage must be available to delete source maps.",
        )


def delete_symbol_set_contents_many(upload_paths: list[str]) -> list[str]:
    if settings.OBJECT_STORAGE_ENABLED:
        return object_storage.delete_objects(file_names=upload_paths)
    else:
        raise ValidationError(
            code="object_storage_required",
            detail="Object storage must be available to delete source maps.",
        )


class ErrorTrackingSpikeDetectionConfig(models.Model):
    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="error_tracking_spike_detection_config",
    )
    snooze_duration_minutes = models.IntegerField(default=10)
    multiplier = models.IntegerField(default=10)
    threshold = models.IntegerField(default=500)

    class Meta:
        db_table = "posthog_errortrackingspikedetectionconfig"


class ErrorTrackingSettings(models.Model):
    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="error_tracking_settings",
    )
    project_rate_limit_value = models.IntegerField(null=True, blank=True)
    project_rate_limit_bucket_size_minutes = models.IntegerField(null=True, blank=True)
    per_issue_rate_limit_value = models.IntegerField(null=True, blank=True)
    per_issue_rate_limit_bucket_size_minutes = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "posthog_errortrackingsettings"


class ErrorTrackingSpikeEvent(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    issue = models.ForeignKey(ErrorTrackingIssue, on_delete=models.CASCADE, related_name="spike_events")
    detected_at = models.DateTimeField()
    computed_baseline = models.FloatField()
    current_bucket_value = models.IntegerField()

    class Meta:
        db_table = "posthog_errortrackingspikeevent"
        indexes = [
            models.Index(fields=["team", "-detected_at"]),
            models.Index(fields=["issue", "-detected_at"]),
            models.Index(fields=["-detected_at"]),
        ]


class ErrorTrackingRecommendation(UUIDTModel):
    """Materialized recommendation for a team, computed asynchronously via Celery."""

    class Status(models.TextChoices):
        READY = "ready", "Ready"
        COMPUTING = "computing", "Computing"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="error_tracking_recommendations")
    # Recommendation type identifier — kept as a free-form CharField rather than a TextChoices enum
    # so adding new recommendations doesn't require a Django migration each time
    type = models.CharField(max_length=64)
    meta = models.JSONField(default=dict, blank=True)
    computed_at = models.DateTimeField(null=True, blank=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.READY)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_errortrackingrecommendation"
        constraints = [
            models.UniqueConstraint(fields=["team", "type"], name="unique_error_tracking_recommendation_per_team_type"),
        ]
