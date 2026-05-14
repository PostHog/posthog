"""DRF serializers for founder_mode.

JSONField columns on `FounderProject` carry stage-specific envelopes. Each envelope's shape
is defined by a Pydantic model in `logic/<stage>/schemas.py`; we attach those models to
typed `JSONField` subclasses via `@extend_schema_field` so drf-spectacular emits real
component schemas in the OpenAPI doc — which then flow through Orval into TypeScript types
and Zod schemas on the frontend. Bare `JSONField` would generate `z.unknown()` instead.
"""

from rest_framework import serializers

from posthog.api.documentation import extend_schema_field

from products.founder_mode.backend.logic.gtm.schemas import GTMEnvelope
from products.founder_mode.backend.logic.hashing import ideation_hash
from products.founder_mode.backend.logic.landing_page.schemas import MarketingPageEnvelope
from products.founder_mode.backend.logic.mvp.schemas import MVPEnvelope
from products.founder_mode.backend.logic.practical_steps.schemas import MarketingStepsEnvelope
from products.founder_mode.backend.logic.scaffold.schemas import ScaffoldEnvelope
from products.founder_mode.backend.logic.validation.schemas import IdeationInput, ValidationEnvelope
from products.founder_mode.backend.models import FounderProject, FounderStepChoices


@extend_schema_field(IdeationInput)  # type: ignore[arg-type]
class IdeationField(serializers.JSONField):
    pass


@extend_schema_field(ValidationEnvelope)  # type: ignore[arg-type]
class ValidationField(serializers.JSONField):
    pass


@extend_schema_field(GTMEnvelope)  # type: ignore[arg-type]
class GTMField(serializers.JSONField):
    pass


@extend_schema_field(MVPEnvelope)  # type: ignore[arg-type]
class MVPField(serializers.JSONField):
    pass


@extend_schema_field(MarketingPageEnvelope)  # type: ignore[arg-type]
class MarketingPageField(serializers.JSONField):
    pass


@extend_schema_field(MarketingStepsEnvelope)  # type: ignore[arg-type]
class MarketingStepsField(serializers.JSONField):
    pass


@extend_schema_field(ScaffoldEnvelope)  # type: ignore[arg-type]
class ScaffoldField(serializers.JSONField):
    pass


class FounderProjectSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        max_length=200,
        help_text='Founder-chosen label for the startup idea, e.g. "AI-powered HOA management".',
    )
    current_step = serializers.ChoiceField(
        choices=FounderStepChoices.choices,
        default=FounderStepChoices.IDEATION,
        help_text=(
            "Which stage the founder is currently on. One of: ideation, validation, gtm, mvp, marketing. "
            "Updated server-side when stages are kicked off, and can be PATCHed by the frontend."
        ),
    )
    ideation = IdeationField(
        required=False,
        help_text=(
            "Stage 1 output. Shape: {what, how, who, problem}. Writing here triggers the "
            "validation Celery task asynchronously."
        ),
    )
    validation = ValidationField(
        read_only=True,
        help_text=(
            "Stage 2 envelope, server-managed. Triggered via the `run_validation` action. "
            "Clients poll the detail endpoint while status is `pending` or `running`."
        ),
    )
    gtm = GTMField(
        read_only=True,
        help_text=(
            "Stage 3 envelope, server-managed. Conceptual GTM summary (positioning, target "
            "segments, pricing tiers, channels). Triggered via the `run_gtm` action."
        ),
    )
    mvp = MVPField(
        read_only=True,
        help_text=(
            "Stage 4 envelope, server-managed. MVP happy-path spec (one-liner, core flow, "
            "must-haves, deliberately-excluded). Triggered via the `run_mvp` action. Schema "
            "is a placeholder and may change."
        ),
    )
    marketing_page = MarketingPageField(
        read_only=True,
        help_text=(
            "Stage 5a envelope, server-managed. Landing page build spec (copy hooks, design "
            "notes, shadcn/ui recipes, PostHog events, acceptance criteria). Triggered via "
            "the `run_landing_page` action."
        ),
    )
    marketing_steps = MarketingStepsField(
        read_only=True,
        help_text=(
            "Stage 5b envelope, server-managed. Practical launch playbook with "
            "ready-to-publish posts for Product Hunt, LinkedIn, Twitter, Reddit, HN, etc. "
            "Triggered via the `run_practical_steps` action."
        ),
    )
    scaffold = ScaffoldField(
        read_only=True,
        help_text=(
            "Stage 6 envelope, server-managed. Two-step pipeline: `run_scaffold` renders "
            "the landing page spec into a single-page static site (`scaffold.files`), then "
            "`publish_scaffold` pushes it to a new GitHub repo AND enables GitHub Pages on "
            "the repo (`scaffold.repo` + `scaffold.pages` with the live URL)."
        ),
    )
    created_by = serializers.PrimaryKeyRelatedField(
        read_only=True,
        help_text="The user who created this founder project. Set automatically on create.",
    )
    ideation_hash = serializers.SerializerMethodField(
        help_text=(
            "Stable SHA-256 of the current ideation payload. Clients compare this to "
            "`validation.ideation_hash` to detect a stale report (founder edited ideation "
            "since the last validation run)."
        ),
    )

    class Meta:
        model = FounderProject
        fields = [
            "id",
            "name",
            "current_step",
            "ideation",
            "ideation_hash",
            "validation",
            "gtm",
            "mvp",
            "marketing_page",
            "marketing_steps",
            "scaffold",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "ideation_hash",
            "validation",
            "gtm",
            "mvp",
            "marketing_page",
            "marketing_steps",
            "scaffold",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def get_ideation_hash(self, obj: FounderProject) -> str:
        return ideation_hash(obj.ideation)
