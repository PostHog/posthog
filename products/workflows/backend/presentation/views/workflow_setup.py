from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.dataclasses import frozen
from posthog.utils import absolute_uri

from products.workflows.backend.facade.contracts import SetupStep
from products.workflows.backend.facade.enums import SetupStepKey
from products.workflows.backend.facade.setup_status import email_sending_paused, get_setup_steps

# The steps an email can't send without. The rest make sending safer or faster but never block it.
_REQUIRED_TO_SEND = (SetupStepKey.CHANNEL, SetupStepKey.DOMAIN)


@frozen
class _StepCopy:
    title: str
    next_step: str
    path: str


_STEP_COPY: dict[SetupStepKey, _StepCopy] = {
    SetupStepKey.CHANNEL: _StepCopy(
        title="Connect an email channel",
        next_step="Add the address emails send from. The person adds it in the app, since it needs a domain they control.",
        path="/workflows/onboarding?path=messaging&step=channel",
    ),
    SetupStepKey.DOMAIN: _StepCopy(
        title="Verify your sending domain",
        next_step="Add the DNS records shown in the app at the domain's DNS provider, then verify. Email sends only from a "
        "verified domain.",
        path="/workflows/onboarding?path=messaging&step=domain",
    ),
    SetupStepKey.OPT_OUTS: _StepCopy(
        title="Add opt-out categories",
        next_step="Let people unsubscribe from one kind of message, such as product updates, and keep the rest.",
        path="/workflows/onboarding?path=messaging&step=opt-outs",
    ),
    SetupStepKey.SENDING_RULES: _StepCopy(
        title="Set a frequency cap",
        next_step="Limit how many marketing emails one person gets across all workflows. The recommended cap is 1 email "
        "every 2 days.",
        path="/settings/environment-workflows#workflows-frequency-cap",
    ),
    SetupStepKey.EMAIL_TEMPLATE: _StepCopy(
        title="Design your first email",
        next_step="Save a reusable email template in the library.",
        path="/workflows/library",
    ),
    SetupStepKey.FIRST_WORKFLOW: _StepCopy(
        title="Create your first workflow",
        next_step="Build a workflow that sends email, SMS or push.",
        path="/workflows/onboarding?path=messaging&step=journey",
    ),
}


class WorkflowSetupStepSerializer(serializers.Serializer):
    key = serializers.ChoiceField(
        choices=SetupStepKey.choices,
        help_text="Which setup step this is. The steps come in the order the setup wizard asks for them.",
    )
    done = serializers.BooleanField(help_text="Whether the project has done this step.")
    title = serializers.CharField(help_text="The step's name, as the app shows it.")
    next_step = serializers.CharField(help_text="What the person does to finish the step.")
    app_url = serializers.CharField(help_text="Link to the place in the app where the person does this step.")


class WorkflowSetupStatusSerializer(serializers.Serializer):
    steps = WorkflowSetupStepSerializer(many=True, help_text="Every messaging setup step, in order.")
    ready_to_send_email = serializers.BooleanField(
        help_text="Whether an email workflow can send. Needs a connected email channel on a verified domain, and "
        "email sending must not be paused for the project. SMS and push use their own channels, and automations "
        "that only post to tools like Slack or call webhooks need none of these steps."
    )
    email_sending_paused = serializers.BooleanField(
        help_text="Whether email sending is paused for the project, so no email sends even with a verified "
        "domain. The person contacts PostHog support to resume it."
    )
    next_open_step = serializers.ChoiceField(
        choices=SetupStepKey.choices,
        allow_null=True,
        help_text="The first step that is not done, or null when every step is done.",
    )


class WorkflowSetupViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Whether a project is set up to send messages from workflows."""

    scope_object = "hog_flow"
    # The status reads the whole project, so access to a single workflow is not enough.
    requires_resource_level_access = True
    scope_object_read_actions = ["status"]

    @extend_schema(operation_id="workflow_setup_status", responses={200: WorkflowSetupStatusSerializer})
    @action(detail=False, methods=["get"])
    def status(self, request: Request, **kwargs: Any) -> Response:
        steps = get_setup_steps(self.team)
        done = {step.key: step.done for step in steps}
        paused = email_sending_paused(self.team)
        return Response(
            WorkflowSetupStatusSerializer(
                {
                    "steps": [self._step(step) for step in steps],
                    "ready_to_send_email": all(done[key] for key in _REQUIRED_TO_SEND) and not paused,
                    "email_sending_paused": paused,
                    "next_open_step": next((step.key for step in steps if not step.done), None),
                }
            ).data
        )

    def _step(self, step: SetupStep) -> dict[str, Any]:
        copy = _STEP_COPY[step.key]
        return {
            "key": step.key,
            "done": step.done,
            "title": copy.title,
            "next_step": copy.next_step,
            "app_url": absolute_uri(f"/project/{self.team.id}{copy.path}"),
        }
