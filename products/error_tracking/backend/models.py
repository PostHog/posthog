from uuid import UUID

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction

from django_deprecate_fields import deprecate_field
from rest_framework.exceptions import ValidationError

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT
from posthog.models.integration import Integration
from posthog.models.utils import UUIDTModel
from posthog.storage import object_storage

from products.error_tracking.backend.sql import INSERT_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES


class ErrorTrackingIssueManager(models.Manager):
    def with_first_seen(self):
        return self.annotate(first_seen=models.Min("fingerprints__first_seen"))


class ErrorTrackingIssue(UUIDTModel):
    class Status(models.TextChoices):
        ARCHIVED = "archived", "Archived"
        ACTIVE = "active", "Active"
        RESOLVED = "resolved", "Resolved"
        PENDING_RELEASE = "pending_release", "Pending release"
        SUPPRESSED = "suppressed", "Suppressed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.TextField(choices=Status.choices, default=Status.ACTIVE, null=False)
    name = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    objects = ErrorTrackingIssueManager()

    class Meta:
        db_table = "posthog_errortrackingissue"

    def merge(self, issue_ids: list[str]) -> None:
        fingerprints = resolve_fingerprints_for_issues(team_id=self.team.pk, issue_ids=issue_ids)

        with transaction.atomic():
            overrides = update_error_tracking_issue_fingerprints(
                team_id=self.team.pk, issue_id=self.id, fingerprints=fingerprints
            )
            ErrorTrackingIssue.objects.filter(team=self.team, id__in=issue_ids).delete()
            update_error_tracking_issue_fingerprint_overrides(team_id=self.team.pk, overrides=overrides)

    def split(self, fingerprints: list[str], exclusive: bool) -> None:
        overrides: list[ErrorTrackingIssueFingerprintV2] = []

        with transaction.atomic():
            common_issue = ErrorTrackingIssue.objects.create(team=self.team) if not exclusive else None
            for fingerprint in fingerprints:
                new_issue = common_issue if common_issue else ErrorTrackingIssue.objects.create(team=self.team)
                overrides.extend(
                    update_error_tracking_issue_fingerprints(
                        team_id=self.team.pk, issue_id=new_issue.id, fingerprints=[fingerprint]
                    )
                )

        update_error_tracking_issue_fingerprint_overrides(team_id=self.team.pk, overrides=overrides)


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
        "posthog.Cohort",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Create a virtual one-to-one relationship constraint we can release later if needed
        constraints = [models.UniqueConstraint(fields=["issue"], name="unique_cohort_for_issue")]
        db_table = "posthog_errortrackingissuecohort"


class ErrorTrackingIssueAssignment(UUIDTModel):
    issue = models.OneToOneField(ErrorTrackingIssue, on_delete=models.CASCADE, related_name="assignment")
    user = models.ForeignKey("posthog.User", null=True, on_delete=models.CASCADE)
    # DEPRECATED: issues can only be assigned to users or roles
    user_group = deprecate_field(models.ForeignKey("posthog.UserGroup", null=True, on_delete=models.CASCADE))
    role = models.ForeignKey("ee.Role", null=True, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_errortrackingissueassignment"


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
            models.Index(fields=["last_used"]),
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Grouping rules are ordered, and greedily evaluated
    order_key = models.IntegerField(null=False, blank=False)

    class Meta:
        indexes = [
            models.Index(fields=["team_id"]),
        ]
        db_table = "posthog_errortrackingsuppressionrule"

        # TODO - I think this is strictly necessary, but I'm not gonna enforce it right now while we're iterating
        # constraints = [
        #     models.UniqueConstraint(fields=["team_id", "order_key"], name="unique_order_key_per_team"),
        # ]


class ErrorTrackingStackFrame(UUIDTModel):
    # Produced by a raw frame
    raw_id = models.TextField(null=False, blank=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    symbol_set = models.ForeignKey("ErrorTrackingSymbolSet", on_delete=models.SET_NULL, null=True)
    contents = models.JSONField(null=False, blank=False)
    resolved = models.BooleanField(null=False, blank=False)
    # The context around the frame, +/- a few lines, if we can get it
    context = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team_id", "raw_id"]),
        ]

        constraints = [
            models.UniqueConstraint(fields=["team_id", "raw_id"], name="unique_raw_id_per_team"),
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
    status = models.CharField(max_length=40, choices=Status.choices, default=Status.ACTIVE, null=False)
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
    team_id: int, issue_id: str, fingerprints: list[str]
) -> list[ErrorTrackingIssueFingerprintV2]:
    return list(
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
    sync: bool = False,
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
        sync=sync,
    )


def delete_symbol_set_contents(upload_path: str) -> None:
    if settings.OBJECT_STORAGE_ENABLED:
        object_storage.delete(file_name=upload_path)
    else:
        raise ValidationError(
            code="object_storage_required",
            detail="Object storage must be available to delete source maps.",
        )
