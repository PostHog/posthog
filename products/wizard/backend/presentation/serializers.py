"""DRF serializers for wizard. Bound to facade DTOs, not Django models."""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.wizard.backend.facade.contracts import UpsertWizardSessionRequest, WizardSessionDTO

# Caps mirror the cloud audit capture (products/tasks run_wizard_audit): the review
# is a nudge built from a handful of findings, so an oversized ledger is truncated,
# not rejected — old or over-eager clients still get their review.
SETUP_REVIEW_MAX_CHECKS = 50
SETUP_REVIEW_MAX_DETAILS_CHARS = 2000

# Ledger bookkeeping rows that aren't setup findings (same set the cloud capture prunes).
SETUP_REVIEW_NON_FINDING_CHECK_IDS = frozenset({"write-report", "upload-notebook"})


class WizardSessionSerializer(DataclassSerializer):
    """Output: serialises a WizardSessionDTO returned by the facade."""

    class Meta:
        dataclass = WizardSessionDTO


class SetupReviewCheckSerializer(serializers.Serializer):
    """One row of the wizard audit's check ledger (.posthog-audit-checks.json)."""

    id = serializers.CharField(max_length=200)
    label = serializers.CharField(max_length=500)  # type: ignore[assignment]
    status = serializers.CharField(max_length=50)
    area = serializers.CharField(max_length=200, required=False, allow_null=True, allow_blank=True)
    file = serializers.CharField(max_length=1000, required=False, allow_null=True, allow_blank=True)
    details = serializers.CharField(required=False, allow_null=True, allow_blank=True, trim_whitespace=False)

    def validate_details(self, value: str | None) -> str | None:
        if not value:
            return None
        return value[:SETUP_REVIEW_MAX_DETAILS_CHARS]


class SetupReviewRequestSerializer(serializers.Serializer):
    """Input: a local wizard audit's check ledger, posted for the signals setup review.

    The cloud counterpart captures the same ledger inside the sandbox
    (products/tasks run_wizard_audit activity); this shape lets an interactive
    local `wizard audit` feed the identical review pipeline.
    """

    repository = serializers.CharField(
        max_length=300,
        help_text=(
            "GitHub repository the audited project lives in, as 'owner/repo'. The signals "
            "pipeline uses it to pick the implementation repo for the review's PRs."
        ),
    )
    checks = SetupReviewCheckSerializer(many=True, allow_empty=False)

    def validate_repository(self, value: str) -> str:
        repository = value.strip()
        parts = repository.split("/")
        if len(parts) != 2 or not all(parts):
            raise serializers.ValidationError("Repository must be in 'owner/repo' format.")
        return repository

    def validate_checks(self, value: list[dict]) -> list[dict]:
        findings = [check for check in value if check["id"] not in SETUP_REVIEW_NON_FINDING_CHECK_IDS]
        return findings[:SETUP_REVIEW_MAX_CHECKS]


class UpsertWizardSessionRequestSerializer(DataclassSerializer):
    """Input: validates the JSON the wizard CLI posts. team_id is derived from URL."""

    class Meta:
        dataclass = UpsertWizardSessionRequest
        extra_kwargs = {
            "session_id": {
                "max_length": 255,
                "help_text": (
                    "Stable identifier the wizard mints for this run "
                    "(format: '{workflow_id}-{skill_id}-{started_at_iso}'). "
                    "Reposting with the same session_id upserts the existing row."
                ),
            },
            "workflow_id": {
                "max_length": 255,
                "help_text": "High-level workflow being run, e.g. 'onboarding', 'migration', 'audit'.",
            },
            "skill_id": {
                "max_length": 255,
                "help_text": "Specific skill within the workflow, e.g. 'nextjs', 'django', 'laravel'.",
            },
            "started_at": {
                "help_text": "UTC timestamp when the wizard started this run. Matches the timestamp encoded in session_id.",
            },
            "run_phase": {
                "help_text": "Lifecycle stage of the wizard run.",
            },
            "event_plan": {
                "help_text": "Optional structured plan of events the wizard intends to instrument. Schema is workflow-specific.",
            },
            "error": {
                "help_text": "Populated when run_phase='error'. Shape: { type: string, message: string }.",
            },
        }
