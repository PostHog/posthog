"""DRF views for founder_mode.

The viewset wires CRUD on FounderProject and one POST action per LLM-backed stage.
Stage actions all share the same shape: validate prerequisites, mark the stage envelope as
`pending`, schedule the Celery task on commit, and return 202 + the serialized project.

# UI stage map

The frontend renders the product as 5 founder-facing stages. They map onto the API like this:

    UI stage          API surface                                Column
    ───────────────   ────────────────────────────────────────   ──────────────────
    1. Ideation       POST cofounder_turn/ (sync chat)           ideation
                      POST founder_projects/ (commit ideation)
    2. Validation     POST {id}/run_validation/                  validation
    3. GTM            POST {id}/run_gtm/                         gtm
                      (conceptual: positioning, pricing, channels)
    4. MVP            POST {id}/run_mvp/                         mvp
                      (happy-path; placeholder prompt today)
    5. Marketing      POST {id}/run_landing_page/                marketing_page
                      POST {id}/run_practical_steps/             marketing_steps
                      (the UI fires both when the founder enters this stage)

Real route registration lives in `posthog/api/__init__.py` — see the `founder_projects`
register call there. presentation/urls.py is a stub kept for documentation symmetry with
other isolated products.
"""

from typing import Any

from django.db import transaction
from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.founder_mode.backend.logic.cofounder_chat.schemas import TurnRequest, TurnResponse
from products.founder_mode.backend.logic.cofounder_chat.service import run_chat_turn
from products.founder_mode.backend.models import FounderProject, FounderStepChoices
from products.founder_mode.backend.tasks.tasks import (
    run_gtm_task,
    run_landing_page_task,
    run_mvp_task,
    run_practical_steps_task,
    run_validation_task,
)

from .serializers import FounderProjectSerializer


@extend_schema(
    tags=["founder_mode"],
    # Override the URL-derived `founder_projects` tag — `custom_postprocessing_hook` in
    # posthog/api/documentation.py auto-appends one segment-derived tag per viewset, which
    # would otherwise split this product across two groups in Swagger UI.
    extensions={"x-swagger-tag": "founder_mode"},
)
@extend_schema_view(
    list=extend_schema(
        description=(
            "List the founder project for the current team (at most one row). Used by the "
            "frontend to find the existing project on session restore."
        ),
    ),
    retrieve=extend_schema(
        description=(
            "Get one founder project by id. **This is the poll target** — the frontend hits "
            "this every 2s while any stage is `running` and renders the appropriate envelope. "
            "One round-trip returns the state of all 5 stages."
        ),
    ),
    create=extend_schema(
        description=(
            "Stage 1 (Ideation) commit. Called by the FE when the cofounder chat reaches "
            "`should_end_chat=true`. Body carries `{name, ideation: {what, how, who, problem}}`. "
            "**Side effect:** if `ideation` is non-empty, validation (stage 2) is auto-fired on "
            "commit — saves a round-trip vs creating then POSTing `run_validation/`. "
            "**Idempotent:** if a project already exists for this team, the existing row is "
            "updated and returned instead of creating a duplicate."
        ),
    ),
    update=extend_schema(
        description=(
            "Full replace. Mainly used for renames. **Side effect:** if `ideation` changes, "
            "validation is re-fired automatically. Avoid sending unchanged ideation — re-runs "
            "burn a Gemini call."
        ),
    ),
    partial_update=extend_schema(
        description=(
            "Patch fields on a founder project. Same auto-revalidation as full update — "
            "sending a changed `ideation` re-fires the validation Celery task. Sending only "
            "`name` (or other non-ideation fields) is the safe rename path."
        ),
    ),
    destroy=extend_schema(
        description="Delete a founder project row. Not wired in the FE today.",
    ),
)
class FounderProjectViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    # `founder_project` lives in OAUTH_HIDDEN_SCOPE_OBJECTS so it's reachable via personal
    # API keys + visible in the docs, but not advertised to OAuth/MCP clients while the
    # product is still alpha. Promote out of OAUTH_HIDDEN once it stabilizes.
    scope_object = "founder_project"
    serializer_class = FounderProjectSerializer
    queryset = FounderProject.objects.all()

    def safely_get_queryset(self, queryset: QuerySet[FounderProject]) -> QuerySet[FounderProject]:
        return queryset.filter(team_id=self.team_id)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Upsert: if a project already exists for this team, update it instead of 409-ing."""
        existing = FounderProject.objects.filter(team_id=self.team_id).first()
        if existing:
            serializer = self.get_serializer(existing, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
            return Response(serializer.data, status=status.HTTP_200_OK)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer: FounderProjectSerializer) -> None:
        instance = serializer.save(team_id=self.team_id, created_by=self.request.user)
        if instance.ideation:
            instance.current_step = FounderStepChoices.VALIDATION
            instance.save(update_fields=["current_step"])
            user_id = self.request.user.id
            transaction.on_commit(lambda: run_validation_task.delay(str(instance.id), user_id))

    def perform_update(self, serializer: FounderProjectSerializer) -> None:
        # Snapshot before save so we can detect whether ideation actually changed.
        # Without this we'd re-run validation on every PATCH (e.g. when stage 3 writes gtm).
        previous_ideation = serializer.instance.ideation
        instance = serializer.save()
        if instance.ideation and instance.ideation != previous_ideation:
            instance.current_step = FounderStepChoices.VALIDATION
            instance.save(update_fields=["current_step"])
            user_id = self.request.user.id
            transaction.on_commit(lambda: run_validation_task.delay(str(instance.id), user_id))

    # Maps stage DB column → the FounderStepChoices value that column belongs to.
    _COLUMN_TO_STEP: dict[str, str] = {
        "validation": FounderStepChoices.VALIDATION,
        "gtm": FounderStepChoices.GTM,
        "mvp": FounderStepChoices.MVP,
        "marketing_page": FounderStepChoices.MARKETING,
        "marketing_steps": FounderStepChoices.MARKETING,
    }

    def _kick_stage(
        self,
        *,
        request: Request,
        column: str,
        task: Any,
        not_ready_detail: str = "Cannot run this stage: ideation is empty.",
    ) -> Response:
        """Shared body for stage kickoff actions.

        Validates ideation is present, eagerly stamps the stage envelope to `pending` so the
        response doesn't briefly show stale terminal state, and schedules the Celery task on
        commit. Returns 202 + the serialized project.
        """
        instance: FounderProject = self.get_object()
        if not instance.ideation:
            return Response({"detail": not_ready_detail}, status=status.HTTP_400_BAD_REQUEST)
        user_id = request.user.id
        transaction.on_commit(lambda: task.delay(str(instance.id), user_id))
        # Eagerly mark `pending` so the response doesn't briefly show prior `completed` state.
        # The task will overwrite to `running` before its first save.
        current = getattr(instance, column) or {}
        setattr(instance, column, {**current, "status": "pending"})
        update_fields = [column, "updated_at"]
        step = self._COLUMN_TO_STEP.get(column)
        if step:
            instance.current_step = step
            update_fields.append("current_step")
        instance.save(update_fields=update_fields)
        return Response(self.get_serializer(instance).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        responses={202: FounderProjectSerializer},
        description=(
            "**Stage 2 (Validation).** Kick off the two-pass competitor research + assumptions "
            "report against the current `ideation` payload. Two sequential Gemini calls — "
            "grounded search, then structured synthesis — ~30-60s end to end. Writes to the "
            "`validation` column with intermediate `current_pass` updates so the FE can show "
            "real staged progress. Poll the detail endpoint until `validation.status` is "
            "`completed` or `failed`."
        ),
    )
    @action(detail=True, methods=["POST"], url_path="run_validation")
    def run_validation(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._kick_stage(
            request=request,
            column="validation",
            task=run_validation_task,
            not_ready_detail="Cannot run validation: ideation is empty.",
        )

    @extend_schema(
        responses={202: FounderProjectSerializer},
        description=(
            "**Stage 3 (GTM).** Generate the *conceptual* GTM summary — positioning statement, "
            "primary + secondary target segments, category, moat, pricing philosophy and "
            "tiers, primary + secondary acquisition channels. Single Gemini call grounded on "
            "`ideation` + `validation.report`. NOT the practical launch playbook (that's "
            "`run_practical_steps`). Writes to the `gtm` column. Poll until `gtm.status` is "
            "`completed` or `failed`."
        ),
    )
    @action(detail=True, methods=["POST"], url_path="run_gtm")
    def run_gtm(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._kick_stage(
            request=request,
            column="gtm",
            task=run_gtm_task,
            not_ready_detail="Cannot run GTM: ideation is empty.",
        )

    @extend_schema(
        responses={202: FounderProjectSerializer},
        description=(
            "**Stage 4 (MVP).** Generate the MVP happy-path spec — one-liner, 3-7 step user "
            "journey from first touch to value delivered, must-have features, deliberately "
            "excluded features. Single Gemini call grounded on `ideation` + `validation` + "
            "`gtm`. Placeholder prompt — content shape may change as stage 4 stabilizes. "
            "Writes to the `mvp` column. Poll until `mvp.status` is `completed` or `failed`."
        ),
    )
    @action(detail=True, methods=["POST"], url_path="run_mvp")
    def run_mvp(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._kick_stage(
            request=request,
            column="mvp",
            task=run_mvp_task,
            not_ready_detail="Cannot run MVP: ideation is empty.",
        )

    @extend_schema(
        responses={202: FounderProjectSerializer},
        description=(
            "**Stage 5 (Marketing) — landing page half.** Generate the landing page *build "
            "spec* (copy hooks, design notes, shadcn/ui component recipes, PostHog event "
            "signatures, acceptance criteria) from the full project state. NOT a rendered "
            "page — a brief a developer or AI coding agent takes and turns into Next.js + "
            "Tailwind code. Writes to the `marketing_page` column. The marketing UI stage "
            "fires this in parallel with `run_practical_steps`. Poll until "
            "`marketing_page.status` is `completed` or `failed`."
        ),
    )
    @action(detail=True, methods=["POST"], url_path="run_landing_page")
    def run_landing_page(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._kick_stage(
            request=request,
            column="marketing_page",
            task=run_landing_page_task,
            not_ready_detail="Cannot generate landing page: ideation is empty.",
        )

    @extend_schema(
        responses={202: FounderProjectSerializer},
        description=(
            "**Stage 5 (Marketing) — practical playbook half.** Generate the concrete launch "
            "checklist — ready-to-publish copy for Product Hunt, LinkedIn, Twitter, Reddit, "
            "HN, Indie Hackers, etc., ordered D-7 → launch day → D+7. Each step has a "
            "platform, timeline, and full post text the founder can copy-paste. Writes to "
            "the `marketing_steps` column. The marketing UI stage fires this in parallel "
            "with `run_landing_page`. Poll until `marketing_steps.status` is `completed` or "
            "`failed`."
        ),
    )
    @action(detail=True, methods=["POST"], url_path="run_practical_steps")
    def run_practical_steps(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._kick_stage(
            request=request,
            column="marketing_steps",
            task=run_practical_steps_task,
            not_ready_detail="Cannot run practical steps: ideation is empty.",
        )

    @extend_schema(
        request=TurnRequest,
        responses={200: TurnResponse},
        description=(
            "**Stage 1 (Ideation).** One turn of a topic-scoped cofounder mini-chat. Synchronous "
            "Gemini call. The request carries `{topic, goal, user_answer, messages, founder_mode}` "
            "— the topic's whole thread so far (chat is ephemeral on the FE). The response carries "
            "the agent's next `agent_message`, a `satisfied` flag, and — when satisfied — a "
            "`crystallized_value` dict whose keys are defined by the request `goal` (for the "
            "`idea` topic: `{what, how, who, problem}`). On `satisfied=true` the FE POSTs the "
            "crystallized value to `founder_projects/` to commit the ideation and auto-fire "
            "validation (stage 2)."
        ),
    )
    @action(detail=False, methods=["POST"], url_path="cofounder_turn")
    def cofounder_turn(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            turn_request = TurnRequest.model_validate(request.data)
        except Exception as exc:
            return Response({"detail": f"Invalid request body: {exc}"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            turn_response, _trace_id = run_chat_turn(
                request=turn_request,
                team=self.team,
                user=request.user,
            )
        except Exception as exc:
            return Response(
                {"detail": f"Cofounder turn failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(turn_response.model_dump(), status=status.HTTP_200_OK)
