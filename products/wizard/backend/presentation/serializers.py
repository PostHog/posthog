"""DRF serializers for wizard. Bound to facade DTOs, not Django models."""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.wizard.backend.facade.contracts import UpsertWizardSessionRequest, WizardSessionDTO


class WizardSessionSerializer(DataclassSerializer):
    """Output: serialises a WizardSessionDTO returned by the facade."""

    class Meta:
        dataclass = WizardSessionDTO


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
