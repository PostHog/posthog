"""The subscription API's writes: the rules a create or an update must pass, the write, and the delivery it starts."""

import uuid
import asyncio
import dataclasses
from collections.abc import Callable
from typing import ClassVar, Optional

from django.conf import settings
from django.db import transaction
from django.db.models import Q

import posthoganalytics
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.schema import SubscriptionAIContextLimit

from posthog.cloud_utils import is_cloud
from posthog.constants import SUBSCRIPTION_AI_PROMPT_FEATURE_FLAG_KEY
from posthog.event_usage import AnalyticsProps, groups
from posthog.exceptions_capture import capture_exception
from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models.integration import SlackIntegration
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User
from posthog.resource_limits import LimitKey, check_count_limit
from posthog.security.url_validation import is_microsoft_teams_webhook_url
from posthog.slo.context import SloSpec, slo_operation
from posthog.slo.types import SloArea, SloOperation
from posthog.temporal.common.client import sync_connect
from posthog.utils import human_list

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.product_analytics.backend.facade.api import insights_including_soft_deleted_for_team
from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.facade.contracts import (
    UNSET,
    ManualDeliveryOutcome,
    ManualDeliveryResult,
    ProcessSubscriptionWorkflowInputs,
    PromptRejectedError,
    SubscriptionContextTarget,
    SubscriptionPermissionDeniedError,
    SubscriptionQuotaExceededError,
    SubscriptionRecord,
    SubscriptionRequestInvalidError,
    SubscriptionTriggerType,
    SubscriptionWrite,
)
from products.subscriptions.backend.logic.auto_disable import validate_re_enable
from products.subscriptions.backend.logic.subscription_query_access import (
    denied_resources_in_subscription,
    should_check_table_access,
)
from products.subscriptions.backend.logic.subscription_utils import MAX_INSIGHTS
from products.subscriptions.backend.logic.teams_subscriptions import (
    TEAMS_WEBHOOK_URL_ERROR,
    TEAMS_WEBHOOK_URL_MASKED_ERROR,
)
from products.subscriptions.backend.models.subscription import Subscription, attribute_subscription_saves
from products.subscriptions.backend.models.subscription_context import SubscriptionContext, context_ref
from products.subscriptions.backend.temporal.ai_subscription.spec_generator import (
    PROMPT_MAX_LENGTH as AI_PROMPT_MAX_LENGTH,
    sanitize_prompt,
)

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

from .subscription_reads import context_rows, subscription_record
from .summary_quota import invalidate_summary_quota_cache, validate_summary_enabled_org_limit
from .visibility import blocked_target_ids, require_viewer_access, viewable_queryset

MAX_AI_SUBSCRIPTION_CONTEXTS: int = int(SubscriptionAIContextLimit.model_fields["root"].default)
AI_DELIVERY_DISPLAY_FIELDS = frozenset(
    {"include_images", "include_feedback", "include_manage_link", "include_posthog_hint"}
)

# The write fields whose model attribute has a different name. Every other field keeps its name.
_MODEL_ATTRIBUTE_NAMES: dict[str, str] = {
    "dashboard_id": "dashboard",
    "insight_id": "insight",
    "dashboard_export_insight_ids": "dashboard_export_insights",
}


def _capture_post_write_failure(exc: Exception) -> None:
    """Report a failure that happens after the write is committed.

    `capture_exception` reads query tags and logs, neither of which is guarded, so a fault in
    reporting would propagate and fail a request whose write already landed.
    """
    try:
        capture_exception(exc)
    except Exception:
        pass


def _ai_create_gate_reason(organization: Organization, distinct_id: str) -> Optional[str]:
    if not settings.DEBUG and not is_cloud():
        return "AI subscriptions are only available in PostHog Cloud."
    if not organization.is_ai_data_processing_approved:
        return "Your organization must approve AI data processing before creating AI subscriptions."
    # Per-user gate so people can self-enable via feature previews (early access) — the flag is
    # person-based. AI credits and the subscription limit stay org-scoped, enforced separately.
    # Non-user callers get a synthetic team_<id> distinct_id that never matches → fails closed.
    if not posthoganalytics.feature_enabled(
        SUBSCRIPTION_AI_PROMPT_FEATURE_FLAG_KEY,
        distinct_id,
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    ):
        return "AI subscriptions are not enabled for your account."
    return None


def _write_attrs(write: SubscriptionWrite) -> dict:
    """The write's fields that are set, keyed the way the model names them.

    The request field checked that a named dashboard or insight exists. Each one resolves to its row
    where validate() checks its team.
    """
    attrs: dict = {}
    for field in dataclasses.fields(write):
        value = getattr(write, field.name)
        if value is UNSET:
            continue
        attrs[_MODEL_ATTRIBUTE_NAMES.get(field.name, field.name)] = value
    return attrs


class _SubscriptionWrite:
    """One create or update, checked against the rules that span fields, the team and the plan."""

    FIELDS_THAT_TRIGGER_REDELIVERY: ClassVar[tuple[str, ...]] = (
        "target_value",
        "target_type",
        "integration_id",
        "delivery_config",
        "prompt",
        "insight_id",
        "dashboard_id",
    )

    def __init__(
        self,
        *,
        team: Team,
        organization: Organization,
        user: User,
        viewer: UserAccessControl,
        instance: Subscription | None,
        partial: bool,
        is_create_request: bool,
        analytics_props: AnalyticsProps,
    ) -> None:
        self.team = team
        self.team_id = team.id
        self.organization = organization
        self.user = user
        self.viewer = viewer
        self.instance = instance
        self.partial = partial
        self.is_create_request = is_create_request
        self.analytics_props = analytics_props

    def _caller_distinct_id(self) -> str:
        if self.user and getattr(self.user, "distinct_id", None):
            return str(self.user.distinct_id)
        return f"team_{self.team_id}"

    def _validate_insight_content(self, attrs: dict, existing: Optional[Subscription]) -> None:
        if not (attrs.get("insight") or (existing and existing.insight_id)):
            raise SubscriptionRequestInvalidError({"insight": ["Insight is required for insight subscriptions."]})
        if attrs.get("dashboard") or attrs.get("prompt"):
            raise SubscriptionRequestInvalidError(
                {"insight": ["Insight subscriptions cannot also set dashboard or prompt."]}
            )

    def _validate_dashboard_content(self, attrs: dict, existing: Optional[Subscription]) -> None:
        if not (attrs.get("dashboard") or (existing and existing.dashboard_id)):
            raise SubscriptionRequestInvalidError({"dashboard": ["Dashboard is required for dashboard subscriptions."]})
        if attrs.get("insight") or attrs.get("prompt"):
            raise SubscriptionRequestInvalidError(
                {"dashboard": ["Dashboard subscriptions cannot also set insight or prompt."]}
            )

    def _validate_ai_content(self, attrs: dict, existing: Optional[Subscription]) -> None:
        if attrs.get("insight") or attrs.get("dashboard"):
            raise SubscriptionRequestInvalidError(
                {"prompt": ["AI subscriptions cannot also set insight or dashboard."]}
            )
        # Explicit-key check so a PATCH sending prompt="" doesn't fall through to the stale value.
        prompt = (attrs["prompt"] if "prompt" in attrs else (existing.prompt if existing else None)) or ""
        prompt = prompt.strip()
        if not prompt:
            raise SubscriptionRequestInvalidError({"prompt": ["Prompt is required for AI subscriptions."]})
        if len(prompt) > AI_PROMPT_MAX_LENGTH:
            raise SubscriptionRequestInvalidError(
                {"prompt": [f"Prompt cannot exceed {AI_PROMPT_MAX_LENGTH} characters."]}
            )
        if "prompt" in attrs:
            attrs["prompt"] = prompt
        target_type = attrs.get("target_type") or (existing.target_type if existing else None)
        if target_type and target_type not in (
            Subscription.SubscriptionTarget.EMAIL,
            Subscription.SubscriptionTarget.SLACK,
            Subscription.SubscriptionTarget.TEAMS,
        ):
            raise SubscriptionRequestInvalidError(
                {"target_type": ["AI subscriptions only support email, slack, or teams delivery."]}
            )
        # Gates fire on create only; existing AI subs stay editable.
        if existing is None:
            gate_reason = _ai_create_gate_reason(self.organization, self._caller_distinct_id())
            if gate_reason is not None:
                raise SubscriptionRequestInvalidError(gate_reason)

    def _validate_contexts(
        self, contexts: tuple[SubscriptionContextTarget, ...]
    ) -> list[dict[str, Insight | Dashboard]]:
        if len(contexts) > MAX_AI_SUBSCRIPTION_CONTEXTS:
            raise SubscriptionRequestInvalidError(
                {"contexts": [f"Select no more than {MAX_AI_SUBSCRIPTION_CONTEXTS} dashboards and insights."]}
            )

        identifiers = [(context.kind, context.id) for context in contexts]
        if len(set(identifiers)) != len(identifiers):
            raise SubscriptionRequestInvalidError({"contexts": ["Select each dashboard or insight only once."]})

        dashboard_ids = {identifier for kind, identifier in identifiers if kind == "dashboard"}
        insight_ids = {identifier for kind, identifier in identifiers if kind == "insight"}
        team_id = self.team.id
        dashboards = {
            dashboard.id: dashboard
            for dashboard in Dashboard.objects_including_soft_deleted.filter(team_id=team_id, id__in=dashboard_ids)
        }
        insights = {
            insight.id: insight
            for insight in insights_including_soft_deleted_for_team(team_id=team_id, insight_ids=insight_ids)
        }
        validated_contexts: list[dict[str, Insight | Dashboard]] = []

        for kind, identifier in identifiers:
            target = dashboards.get(identifier) if kind == "dashboard" else insights.get(identifier)
            if target is None:
                raise SubscriptionRequestInvalidError(
                    {"contexts": [f"This {kind} is not in your team, or no longer exists."]}
                )
            if target.deleted:
                raise SubscriptionRequestInvalidError({"contexts": [f"This {kind} has been deleted."]})
            if not self.viewer.check_access_level_for_object(target, "viewer"):
                raise SubscriptionRequestInvalidError(
                    {"contexts": [f"Viewer access to this {kind} is required. Ask an admin to grant you access."]}
                )
            if isinstance(target, Dashboard):
                self._require_viewer_access_to_every_live_tile(target, error_field="contexts")
            validated_contexts.append({kind: target})

        return validated_contexts

    def validate(self, attrs: dict) -> dict:
        # Re-run the free-tier cap on create AND on restore (deleted: true → false) —
        # a soft-deleted row frees its slot, so PATCHing one back to active re-occupies
        # one and must respect the limit, otherwise a free-tier team could soft-delete +
        # create + restore its way past the cap.
        is_create = self.is_create_request
        is_restoring = self.instance is not None and self.instance.deleted and attrs.get("deleted") is False
        if is_create or is_restoring:
            msg = Subscription.check_subscription_limit(self.team_id, self.organization)
            if msg:
                raise SubscriptionRequestInvalidError({"subscription": [msg]})

        existing = self.instance

        if attrs.get("dashboard"):
            # Looked up in any team, so a dashboard of another team gets this error rather than a missing-row error.
            # nosemgrep: idor-lookup-without-team
            attrs["dashboard"] = Dashboard.objects.get(pk=attrs["dashboard"])
            if attrs["dashboard"].team.id != self.team_id:
                raise SubscriptionRequestInvalidError({"dashboard": ["This dashboard does not belong to your team."]})

        if attrs.get("insight"):
            # An insight of another project is not returned, and one of a sibling environment fails the team check.
            team_insights = insights_including_soft_deleted_for_team(
                team_id=self.team_id, insight_ids=[attrs["insight"]]
            )
            if not team_insights or team_insights[0].team.id != self.team_id:
                raise SubscriptionRequestInvalidError({"insight": ["This insight does not belong to your team."]})
            attrs["insight"] = team_insights[0]

        turning_off = attrs.get("deleted") is True or attrs.get("enabled") is False
        for field in ("dashboard", "insight"):
            target = attrs.get(field) or getattr(existing, field, None)
            if target is not None and not (target.deleted and turning_off):
                require_viewer_access(self.viewer, target, field)

        if existing is None:
            # Create: a subscription must export an insight, a dashboard, or an AI prompt.
            if not attrs.get("dashboard") and not attrs.get("insight") and not attrs.get("prompt"):
                raise SubscriptionRequestInvalidError("A subscription must have an insight, a dashboard, or a prompt.")

        try:
            if existing is not None:
                # `resource_type` derives from the row's content; a corrupt row (e.g. a prompt
                # nulled directly in the DB) leaves nothing to derive from and raises.
                resource_type = existing.resource_type
            else:
                insight, dashboard = attrs.get("insight"), attrs.get("dashboard")
                resource_type = Subscription.derive_resource_type(
                    insight.id if insight else None, dashboard.id if dashboard else None, attrs.get("prompt")
                )
        except ValueError as exc:
            raise SubscriptionRequestInvalidError(str(exc))
        # The prompt merge below folds the stored config into `attrs`, so keep what the caller
        # actually sent. A stored option that the request never names must not reject the
        # request, because that leaves the row impossible to edit.
        submitted_delivery_config = attrs.get("delivery_config") or {}
        if (
            resource_type == Subscription.ResourceType.AI_PROMPT
            and self.partial
            and existing is not None
            and "delivery_config" in attrs
        ):
            existing_delivery_config = existing.delivery_config if isinstance(existing.delivery_config, dict) else {}
            attrs["delivery_config"] = {**existing_delivery_config, **attrs["delivery_config"]}
        content_validators: dict[str, Callable[[dict, Optional[Subscription]], None]] = {
            Subscription.ResourceType.INSIGHT: self._validate_insight_content,
            Subscription.ResourceType.DASHBOARD: self._validate_dashboard_content,
            Subscription.ResourceType.AI_PROMPT: self._validate_ai_content,
        }
        validate_for_resource_type = content_validators.get(resource_type)
        # Fail soft on an unexpected resource_type (e.g. a stale DB row) — a 400 is
        # diagnosable, an unhandled KeyError surfaces as a 500.
        if validate_for_resource_type is None:
            raise SubscriptionRequestInvalidError({"resource_type": [f"Unsupported resource_type: {resource_type}."]})
        if resource_type != Subscription.ResourceType.AI_PROMPT and attrs.get("ai_prompt_config"):
            raise SubscriptionRequestInvalidError(
                {
                    "ai_prompt_config": [
                        "ai_prompt_config only applies to prompt subscriptions. This subscription has "
                        f"resource_type '{resource_type}', so remove it from the request."
                    ]
                }
            )
        if "contexts" in attrs:
            if resource_type != Subscription.ResourceType.AI_PROMPT:
                if attrs["contexts"]:
                    raise SubscriptionRequestInvalidError({"contexts": ["Context only applies to AI subscriptions."]})
                # Every read carries an empty list here, so a client saving what it read sends one back.
                attrs.pop("contexts")
            else:
                attrs["contexts"] = self._validate_contexts(attrs["contexts"])
        validate_for_resource_type(attrs, existing)

        self._validate_dashboard_export_subscription(attrs)

        target_type = attrs.get("target_type") or (self.instance.target_type if self.instance else None)
        if (
            self.instance
            and self.instance.target_type == Subscription.SubscriptionTarget.TEAMS
            and target_type != Subscription.SubscriptionTarget.TEAMS
            and "target_value" not in attrs
        ):
            raise SubscriptionRequestInvalidError(
                {"target_value": ["A new target value is required when changing from Microsoft Teams."]}
            )
        # Use explicit-key check for integration_id so a deliberate `null` in the PATCH
        # body falls through to the validation below — `or` would silently coalesce
        # to the stale instance value and pass `validate_re_enable` with the wrong id.
        integration_id = (
            attrs["integration_id"]
            if "integration_id" in attrs
            else (self.instance.integration_id if self.instance else None)
        )
        effective_delivery_config = (
            attrs["delivery_config"]
            if "delivery_config" in attrs
            else (self.instance.delivery_config if self.instance else None)
        ) or {}
        # A prompt report never reads the gallery option, so only the value a request sends can be
        # wrong. An insight or dashboard report does read it, so the stored value still decides: a
        # target or permission change would break the next delivery.
        gallery_enabled = (
            submitted_delivery_config
            if resource_type == Subscription.ResourceType.AI_PROMPT
            else effective_delivery_config
        ).get("post_all_insights_in_main_message")
        if resource_type != Subscription.ResourceType.AI_PROMPT:
            unsupported = sorted(AI_DELIVERY_DISPLAY_FIELDS & submitted_delivery_config.keys())
            if unsupported:
                verb, pronoun = ("applies", "it") if len(unsupported) == 1 else ("apply", "them")
                raise SubscriptionRequestInvalidError(
                    {
                        "delivery_config": [
                            f"{human_list(unsupported)} only {verb} to prompt subscriptions. "
                            f"This subscription has resource_type '{resource_type}', "
                            f"so remove {pronoun} from delivery_config."
                        ]
                    }
                )
        elif gallery_enabled:
            # The prompt Slack renderer already posts every chart in the main message and never reads this option.
            raise SubscriptionRequestInvalidError(
                {
                    "delivery_config": [
                        "post_all_insights_in_main_message only applies to insight and dashboard "
                        f"subscriptions. This subscription has resource_type '{resource_type}', so "
                        "remove it from delivery_config. A prompt report already posts all its chart "
                        "images in the main message."
                    ]
                }
            )

        # Reject re-enables of subscriptions whose delivery prerequisite is still
        # permanently broken — otherwise the next delivery would just auto-disable
        # them again.
        is_re_enabling = self.instance is not None and attrs.get("enabled") is True and self.instance.enabled is False
        if is_re_enabling:
            error_message = validate_re_enable(target_type, integration_id)
            if error_message:
                raise SubscriptionRequestInvalidError({"enabled": [error_message]})
            # AI subs auto-disable on PromptRejectedError (deleted creator, prompt now
            # fails sanitization). The delivery path will just re-disable on the next
            # tick unless the underlying cause is fixed by this PATCH.
            if resource_type == Subscription.ResourceType.AI_PROMPT:
                prompt_after = attrs.get("prompt") if "prompt" in attrs else (existing.prompt if existing else None)
                created_by_after = existing.created_by if existing else None
                if created_by_after is None:
                    raise SubscriptionRequestInvalidError(
                        {"enabled": ["Cannot re-enable AI subscription: the original creator is unavailable."]}
                    )
                try:
                    sanitize_prompt(prompt_after)
                except PromptRejectedError as exc:
                    raise SubscriptionRequestInvalidError(
                        {"enabled": [f"Cannot re-enable AI subscription: prompt is invalid ({exc})."]}
                    )

        # Reject mutations that would land `next_delivery_date=None` — `enabled=True`
        # with a null next_delivery_date is invisible to the scheduler (the
        # `__lte=now` filter in `fetch_due_subscriptions_activity` drops nulls).
        # Three reachable paths: re-enable an exhausted sub, create one with a bad
        # rrule, or PATCH an active sub's schedule into exhaustion.
        check_schedule = (
            is_re_enabling
            or self.instance is None
            or (self.instance is not None and self.instance.enabled and bool(Subscription.RRULE_FIELDS & attrs.keys()))
        )
        if check_schedule and Subscription.project_next_delivery_date(instance=self.instance, **attrs) is None:
            base = "Subscription schedule has reached its end date. Extend until_date or remove count"
            if is_re_enabling:
                raise SubscriptionRequestInvalidError({"enabled": [f"{base} before re-enabling."]})
            if self.instance is None:
                raise SubscriptionRequestInvalidError({"start_date": [f"{base}."]})
            raise SubscriptionRequestInvalidError(f"{base}.")

        if target_type == Subscription.SubscriptionTarget.TEAMS:
            submitted = (attrs.get("target_value") or "").strip()
            if self.instance and submitted and submitted == self.instance.recipient_label:
                raise SubscriptionRequestInvalidError({"target_value": [TEAMS_WEBHOOK_URL_MASKED_ERROR]})
            target_value = submitted or (self.instance.target_value if self.instance else "")
            if not is_microsoft_teams_webhook_url(target_value):
                raise SubscriptionRequestInvalidError({"target_value": [TEAMS_WEBHOOK_URL_ERROR]})

        if target_type == Subscription.SubscriptionTarget.SLACK:
            if not integration_id:
                raise SubscriptionRequestInvalidError(
                    {"integration_id": ["A Slack integration is required for Slack subscriptions."]}
                )
            try:
                integration = IntegrationManager.slack.oauth.get(self.team_id, integration_id)
            except IntegrationNotFound:
                raise SubscriptionRequestInvalidError(
                    {"integration_id": ["This integration does not exist or does not belong to your team."]}
                )
            if gallery_enabled and SlackIntegration(integration).missing_scopes({"files:write"}):
                raise SubscriptionRequestInvalidError(
                    {
                        "delivery_config": [
                            "post_all_insights_in_main_message requires the Slack files:write permission. "
                            "Reconnect Slack to grant it, or remove the option from delivery_config to "
                            "save the subscription now. Each delivery then posts the first image in the "
                            "main message and the rest as threaded replies."
                        ]
                    }
                )

        if gallery_enabled and target_type != Subscription.SubscriptionTarget.SLACK:
            raise SubscriptionRequestInvalidError(
                {
                    "delivery_config": [
                        "post_all_insights_in_main_message only applies to Slack subscriptions. "
                        f"This subscription delivers to {target_type}, so remove it from delivery_config."
                    ]
                }
            )

        prompt_guide = attrs.get("summary_prompt_guide")
        if prompt_guide and len(prompt_guide) > 500:
            raise SubscriptionRequestInvalidError(
                {"summary_prompt_guide": ["AI summary context must be 500 characters or fewer."]}
            )

        if attrs.get("summary_enabled"):
            if not self.organization.is_ai_data_processing_approved:
                raise SubscriptionPermissionDeniedError(
                    "AI data processing must be approved by your organization before enabling AI summaries"
                )

        # Cap gate: fire whenever the row is *becoming* an active summary
        # (summary_enabled=True AND deleted=False) but wasn't before. This
        # catches creates with the toggle on, off→on transitions, AND
        # restoring a soft-deleted summary that was already summary_enabled
        # — otherwise PATCHing `deleted=False` on a grandfathered row would
        # bypass the cap entirely.
        if self._is_becoming_active_summary(attrs):
            self._validate_summary_credit_budget()
            validate_summary_enabled_org_limit(
                self.organization,
                team_id=self.team_id,
                caller_distinct_id=self._caller_distinct_id(),
                is_create=self.instance is None,
            )

        self._check_query_access(attrs, resource_type)

        return attrs

    def _check_query_access(self, attrs: dict, resource_type: str) -> None:
        if resource_type == Subscription.ResourceType.AI_PROMPT:
            return
        subscription_id = self.instance.id if self.instance else None
        if not should_check_table_access(team_id=self.team_id, subscription_id=subscription_id, attrs=attrs):
            return
        # Compiling the queries as the requester needs a real user. The view passes the request's
        # user cast to User, so a synthetic user can still arrive here.
        requester: object = self.user
        if not isinstance(requester, User):
            return
        denied_resources = denied_resources_in_subscription(
            user=requester,
            team=self.team,
            user_access_control=self.viewer,
            subscription_id=subscription_id,
            attrs=attrs,
        )
        if denied_resources:
            denied_names = ", ".join(f"`{name}`" for name in denied_resources)
            raise SubscriptionRequestInvalidError(
                f"Can't save this subscription: you don't have access to {denied_names}."
            )

    def _is_becoming_active_summary(self, attrs: dict) -> bool:
        pre_summary_enabled = self.instance.summary_enabled if self.instance else False
        pre_deleted = self.instance.deleted if self.instance else False
        post_summary_enabled = attrs.get("summary_enabled", pre_summary_enabled)
        post_deleted = attrs.get("deleted", pre_deleted)

        pre_active = pre_summary_enabled and not pre_deleted
        post_active = post_summary_enabled and not post_deleted
        return post_active and not pre_active

    def _validate_summary_credit_budget(self) -> None:
        # Refuse to turn a summary on while the org is over its AI credit budget,
        # mirroring the chat assistant's gate (ee/api/conversation.py).
        if is_team_limited(self.team.api_token, QuotaResource.AI_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY):
            raise SubscriptionQuotaExceededError(
                "Your organization reached its AI credit usage limit. "
                "Increase the limits in Billing settings, or ask an org admin to do so."
            )

    def _validate_dashboard_export_subscription(self, attrs: dict) -> None:
        dashboard = attrs.get("dashboard") or (self.instance.dashboard if self.instance else None)
        if dashboard is None:
            # Reject dashboard_export_insights on non dashboard subscriptions
            if attrs.get("dashboard_export_insights"):
                raise SubscriptionRequestInvalidError(
                    {"dashboard_export_insights": ["Cannot set insights selection without a dashboard."]}
                )
            return

        # For PATCH requests, dashboard_export_insights might not be in attrs - only validate if provided or on create
        dashboard_export_insights_provided = "dashboard_export_insights" in attrs
        dashboard_export_insights = attrs.get("dashboard_export_insights", [])

        is_create = self.instance is None
        if (
            # For new dashboard subscriptions, require at least one insight to be selected
            (is_create and not dashboard_export_insights)
            or
            # If updating and explicitly setting dashboard_export_insights to empty, reject it
            (not is_create and dashboard_export_insights_provided and not dashboard_export_insights)
        ):
            raise SubscriptionRequestInvalidError(
                {"dashboard_export_insights": ["Select at least one insight for this subscription."]}
            )

        if dashboard_export_insights:
            selected_ids = set(dashboard_export_insights)

            if len(selected_ids) > MAX_INSIGHTS:
                raise SubscriptionRequestInvalidError(
                    {"dashboard_export_insights": [f"Cannot select more than {MAX_INSIGHTS} insights."]}
                )

            team_insights = Insight.objects.filter(id__in=selected_ids, team_id=self.team_id)
            viewable_ids = set(viewable_queryset(self.viewer, team_insights, "insight").values_list("id", flat=True))
            unusable_ids = selected_ids - viewable_ids
            if unusable_ids:
                if team_insights.count() != len(selected_ids):
                    raise SubscriptionRequestInvalidError(
                        {"dashboard_export_insights": ["Some insights are not in your team, or no longer exist."]}
                    )
                raise SubscriptionRequestInvalidError(
                    {
                        "dashboard_export_insights": [
                            "Viewer access to every selected insight is required. "
                            "Ask an admin for access, or remove the restricted insights."
                        ]
                    }
                )

            # Ensure all selected insights belong to the dashboard (and are not deleted)
            dashboard_insight_ids = set(
                dashboard.tiles.filter(insight__isnull=False, insight__deleted=False).values_list(
                    "insight_id", flat=True
                )
            )
            invalid_ids = selected_ids - dashboard_insight_ids

            if invalid_ids:
                raise SubscriptionRequestInvalidError(
                    {"dashboard_export_insights": [f"{len(invalid_ids)} invalid insight(s) selected."]}
                )
            return

        if self._keeps_its_own_selection():
            return

        self._require_viewer_access_to_every_live_tile(dashboard)

    def _keeps_its_own_selection(self) -> bool:
        return self.instance is not None and self.instance.dashboard_export_insights.exists()

    def _require_viewer_access_to_every_live_tile(
        self, dashboard: Dashboard, *, error_field: str = "dashboard"
    ) -> None:
        live_tile_insights = Insight.objects.filter(
            team_id=self.team_id,
            id__in=dashboard.tiles.filter(insight__isnull=False, insight__deleted=False).values("insight_id"),
        )
        if blocked_target_ids(self.viewer, live_tile_insights, "insight").exists():
            raise SubscriptionRequestInvalidError(
                {
                    error_field: [
                        "Viewer access to every insight on this dashboard is required. "
                        "Ask an admin for access, or select only the insights you can view."
                    ]
                }
            )

    @staticmethod
    def _context_identifiers(contexts: list[dict[str, Insight | Dashboard]]) -> set[tuple[str, int]]:
        return {(kind, target.id) for context in contexts for kind, target in context.items()}

    @staticmethod
    def _stored_context_identifiers(instance: Subscription) -> set[tuple[str, int]]:
        identifiers: set[tuple[str, int]] = set()
        for context in context_rows(instance):
            if context.dashboard_id is not None:
                identifiers.add(("dashboard", context.dashboard_id))
            elif context.insight_id is not None:
                identifiers.add(("insight", context.insight_id))
        return identifiers

    @staticmethod
    def _replaceable_context_identifiers(instance: Subscription) -> set[tuple[str, int]]:
        identifiers: set[tuple[str, int]] = set()
        for context in context_rows(instance):
            if not context.has_target_for_team(context.team_id, include_deleted=True):
                continue

            if context.dashboard_id is not None:
                identifiers.add(("dashboard", context.dashboard_id))
            elif context.insight_id is not None:
                identifiers.add(("insight", context.insight_id))
        return identifiers

    @staticmethod
    def _context_refs(identifiers: set[tuple[str, int]]) -> list[str]:
        return sorted(context_ref(kind, identifier) for kind, identifier in identifiers)

    @staticmethod
    def _replace_contexts(instance: Subscription, contexts: list[dict[str, Insight | Dashboard]]) -> None:
        context_team_id = instance.team.parent_team_id or instance.team_id
        scoped_contexts = SubscriptionContext.objects.for_team(context_team_id, canonical=True)
        scoped_contexts.filter(subscription=instance).filter(
            Q(dashboard__team_id=context_team_id) | Q(insight__team_id=context_team_id)
        ).delete()
        for context in contexts:
            scoped_contexts.create(team_id=context_team_id, subscription=instance, **context)
        getattr(instance, "_prefetched_objects_cache", {}).pop("contexts", None)

    @staticmethod
    def _save(instance: Subscription, validated_data: dict) -> Subscription:
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

    def _update_with_contexts(
        self,
        instance: Subscription,
        validated_data: dict,
        contexts: list[dict[str, Insight | Dashboard]],
        contexts_in_payload: bool,
        analytics_props: AnalyticsProps,
    ) -> tuple[Subscription, bool]:
        contexts_changed = False
        context_change: tuple[list[str], list[str]] | None = None
        with transaction.atomic():
            if contexts_in_payload:
                instance = Subscription.objects.select_for_update().get(pk=instance.pk)
                stored_identifiers = self._stored_context_identifiers(instance)
                preserved_identifiers = stored_identifiers - self._replaceable_context_identifiers(instance)
                updated_identifiers = preserved_identifiers | self._context_identifiers(contexts)
                contexts_changed = stored_identifiers != updated_identifiers
                if contexts_changed:
                    context_change = (
                        self._context_refs(stored_identifiers),
                        self._context_refs(updated_identifiers),
                    )
            with attribute_subscription_saves(analytics_props, context_change=context_change):
                instance = self._save(instance, validated_data)
            if contexts_changed:
                self._replace_contexts(instance, contexts)
        return instance, contexts_changed

    def create(self, validated_data: dict) -> Subscription:
        validated_data["team_id"] = self.team_id
        validated_data["created_by"] = self.user
        team = self.team
        current_count = Subscription.objects.filter(team_id=team.id, deleted=False).count()
        check_count_limit(
            team=team,
            key=LimitKey.MAX_SUBSCRIPTIONS_PER_TEAM,
            current_count=current_count,
            user=self.user,
        )

        invite_message = validated_data.pop("invite_message", "")
        # The immediate confirmation delivery (SUBSCRIPTION_CHANGE below) is separate from the
        # recurring schedule, which the scheduler drives off next_delivery_date. Creators
        # can opt out of that first send via send_test_now; the schedule is unaffected.
        send_test_now = validated_data.pop("send_test_now", True)
        dashboard_export_insight_ids = validated_data.pop("dashboard_export_insights", [])
        contexts = validated_data.pop("contexts", [])
        with transaction.atomic():
            context_identifiers = self._context_identifiers(contexts)
            context_change: tuple[list[str], list[str]] | None = (
                ([], self._context_refs(context_identifiers)) if context_identifiers else None
            )
            with attribute_subscription_saves(self.analytics_props, context_change=context_change):
                instance: Subscription = Subscription.objects.create(**validated_data)
            self._replace_contexts(instance, contexts)

        # Bust the org-wide active-summary count cache so the next quota
        # fetch reflects this row, regardless of summary_enabled — over-busting
        # is cheap and removes the need to track the prior state.
        invalidate_summary_quota_cache(instance.team.organization_id)

        if dashboard_export_insight_ids:
            instance.dashboard_export_insights.set(dashboard_export_insight_ids)

        if not instance.enabled or not send_test_now:
            return instance

        # The row is committed above and the schedule runs off next_delivery_date, so failing the
        # request here would hide a subscription that exists and make the retry create a second one.
        try:
            with slo_operation(
                spec=SloSpec(
                    distinct_id=str(self.user.distinct_id),
                    area=SloArea.ANALYTIC_PLATFORM,
                    operation=SloOperation.SUBSCRIPTION_CREATE,
                    team_id=instance.team_id,
                    resource_id=str(instance.id),
                ),
                properties={
                    "subscription_id": instance.id,
                    "target_type": instance.target_type,
                    "frequency": instance.frequency,
                    "interval": instance.interval,
                    "byweekday": instance.byweekday,
                    "bysetpos": instance.bysetpos,
                    "count": instance.count,
                    "resource_type": instance.resource_type,
                    "dashboard_export_insights_count": len(dashboard_export_insight_ids),
                    "summary_enabled": instance.summary_enabled,
                    "has_summary_prompt_guide": bool(instance.summary_prompt_guide),
                    "has_until_date": instance.until_date is not None,
                    "has_invite_message": bool(invite_message),
                },
            ):
                temporal = sync_connect()
                workflow_id = f"handle-subscription-value-change-{instance.id}-{uuid.uuid4()}"
                asyncio.run(
                    temporal.start_workflow(
                        "handle-subscription-value-change",
                        ProcessSubscriptionWorkflowInputs(
                            subscription_id=instance.id,
                            team_id=instance.team_id,
                            distinct_id=str(instance.created_by.distinct_id)
                            if instance.created_by
                            else str(instance.team_id),
                            previous_target_value="",
                            previous_value="",
                            invite_message=invite_message,
                            trigger_type=SubscriptionTriggerType.SUBSCRIPTION_CHANGE,
                            resource_type=instance.resource_type,
                        ),
                        id=workflow_id,
                        task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
                    )
                )
        except Exception as exc:
            _capture_post_write_failure(exc)

        return instance

    def update(self, instance: Subscription, validated_data: dict) -> Subscription:
        previous_target_value = instance.target_value
        was_disabled = instance.enabled is False
        is_delete = not instance.deleted and validated_data.get("deleted") is True
        invite_message = validated_data.pop("invite_message", "")
        # None means "not provided" — the delivery decision then falls back to inferring from
        # what the edit changed, matching the long-standing default behavior.
        send_test_now: bool | None = validated_data.pop("send_test_now", None)
        # Track payload PRESENCE, not truthiness: an empty list (clearing all exports) is delivery-relevant
        # too, so `bool(ids)` would miss it. Pop loses presence, so capture it first.
        export_insights_in_payload = "dashboard_export_insights" in validated_data
        dashboard_export_insight_ids = validated_data.pop("dashboard_export_insights", [])
        contexts_in_payload = "contexts" in validated_data
        contexts = validated_data.pop("contexts", [])
        contexts_changed = False
        analytics_props = self.analytics_props

        # Snapshot delivery-relevant values before the write so the inferred path can tell,
        # after, whether the edit actually changed what gets delivered. Only snapshot the
        # dashboard_export_insights M2M when the payload carries it — that's the only case
        # `.set()` can mutate the relation, so a schedule/meta-only edit pays no M2M query.
        old_delivery_values = {field: getattr(instance, field) for field in self.FIELDS_THAT_TRIGGER_REDELIVERY}
        old_export_insight_ids = (
            set(instance.dashboard_export_insights.values_list("id", flat=True)) if export_insights_in_payload else None
        )

        if is_delete:
            with slo_operation(
                spec=SloSpec(
                    distinct_id=str(self.user.distinct_id),
                    area=SloArea.ANALYTIC_PLATFORM,
                    operation=SloOperation.SUBSCRIPTION_DELETE,
                    team_id=instance.team_id,
                    resource_id=str(instance.id),
                ),
                properties={
                    "subscription_id": instance.id,
                    "target_type": instance.target_type,
                    "frequency": instance.frequency,
                    "resource_type": instance.resource_type,
                },
            ):
                instance, contexts_changed = self._update_with_contexts(
                    instance, validated_data, contexts, contexts_in_payload, analytics_props
                )
            invalidate_summary_quota_cache(instance.team.organization_id)
            return instance

        instance, contexts_changed = self._update_with_contexts(
            instance, validated_data, contexts, contexts_in_payload, analytics_props
        )
        invalidate_summary_quota_cache(instance.team.organization_id)

        # Apply the M2M whenever the field is in the payload — including an empty list, which clears it.
        if export_insights_in_payload:
            instance.dashboard_export_insights.set(dashboard_export_insight_ids)

        is_re_enabling = was_disabled and instance.enabled

        # Re-enabling clears the stale next_delivery_date that was frozen while
        # disabled. Without this, the scheduler picks the sub up on its next tick
        # (the past date matches `next_delivery_date__lte=now`) and fires a second
        # SCHEDULED delivery right after the immediate SUBSCRIPTION_CHANGE confirmation.
        if is_re_enabling:
            instance.set_next_delivery_date()
            instance.save(update_fields=["next_delivery_date"])

        delivery_content_changed = any(
            getattr(instance, field) != old_value for field, old_value in old_delivery_values.items()
        ) or (old_export_insight_ids is not None and set(dashboard_export_insight_ids) != old_export_insight_ids)
        delivery_content_changed = delivery_content_changed or contexts_changed

        # Explicit send_test_now wins. When omitted, infer: send when the edit changed what
        # gets delivered, or on re-enable — a schedule/meta-only edit must not push a fresh
        # delivery. Disabled subscriptions never fire regardless.
        wants_delivery = send_test_now if send_test_now is not None else (is_re_enabling or delivery_content_changed)
        delivery_triggered = wants_delivery and instance.enabled

        # Explicit observability for the delivery decision on edits — the canonical
        # "subscription updated" event fires from the post_save signal before this decision
        # exists, so a regression that silently suppressed deliveries would be invisible there.
        posthoganalytics.capture(
            distinct_id=str(self.user.distinct_id),
            event="subscription_update_delivery_intent",
            properties={
                **analytics_props,
                "subscription_id": instance.id,
                "team_id": instance.team_id,
                "resource_type": instance.resource_type,
                "send_test_now": send_test_now,
                "delivery_triggered": delivery_triggered,
                "re_enabled": is_re_enabling,
                "subscription_enabled": instance.enabled,
            },
            groups=groups(None, instance.team),
        )

        if not delivery_triggered:
            return instance

        if send_test_now:
            # Explicit ask: deterministic ID so a caller spamming send_test_now dedupes to one
            # in-flight delivery per subscription instead of fanning out real sends. Kept distinct
            # from the test-delivery action's ID family so the two flows stay tellable apart.
            workflow_id = f"send-test-now-subscription-{instance.id}"
        else:
            # Inferred delivery (recipient/target change, re-enable): unique ID so two legitimate
            # consecutive edits both deliver instead of the second silently deduping.
            workflow_id = f"handle-subscription-value-change-{instance.id}-{uuid.uuid4()}"
        try:
            temporal = sync_connect()
            asyncio.run(
                temporal.start_workflow(
                    "handle-subscription-value-change",
                    ProcessSubscriptionWorkflowInputs(
                        subscription_id=instance.id,
                        team_id=instance.team_id,
                        distinct_id=str(instance.created_by.distinct_id)
                        if instance.created_by
                        else str(instance.team_id),
                        previous_target_value=previous_target_value,
                        previous_value=previous_target_value,
                        invite_message=invite_message,
                        trigger_type=SubscriptionTriggerType.SUBSCRIPTION_CHANGE,
                        resource_type=instance.resource_type,
                    ),
                    id=workflow_id,
                    task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
                )
            )
        except WorkflowAlreadyStartedError:
            # A delivery for this subscription is already in flight; the update itself
            # succeeded, so skip the duplicate send rather than failing the request.
            pass
        except Exception as exc:
            _capture_post_write_failure(exc)

        return instance


def create_subscription(
    *,
    team: Team,
    organization: Organization,
    user: User,
    viewer: UserAccessControl,
    write: SubscriptionWrite,
    analytics_props: AnalyticsProps,
) -> SubscriptionRecord:
    subscription_write = _SubscriptionWrite(
        team=team,
        organization=organization,
        user=user,
        viewer=viewer,
        instance=None,
        partial=False,
        is_create_request=True,
        analytics_props=analytics_props,
    )
    validated_data = subscription_write.validate(_write_attrs(write))
    return subscription_record(subscription_write.create(validated_data))


def update_subscription(
    *,
    team: Team,
    organization: Organization,
    user: User,
    viewer: UserAccessControl,
    subscription_id: int,
    write: SubscriptionWrite,
    partial: bool,
    analytics_props: AnalyticsProps,
) -> SubscriptionRecord:
    instance = Subscription.objects.get(pk=subscription_id, team_id=team.id)
    subscription_write = _SubscriptionWrite(
        team=team,
        organization=organization,
        user=user,
        viewer=viewer,
        instance=instance,
        partial=partial,
        is_create_request=False,
        analytics_props=analytics_props,
    )
    validated_data = subscription_write.validate(_write_attrs(write))
    return subscription_record(subscription_write.update(instance, validated_data))


def start_test_delivery(*, team_id: int, subscription_id: int) -> ManualDeliveryResult:
    subscription = Subscription.objects.get(pk=subscription_id, team_id=team_id)
    temporal = sync_connect()
    workflow_id = f"test-delivery-subscription-{subscription.id}"
    try:
        asyncio.run(
            temporal.start_workflow(
                "handle-subscription-value-change",
                ProcessSubscriptionWorkflowInputs(
                    subscription_id=subscription.id,
                    team_id=subscription.team_id,
                    distinct_id=str(subscription.created_by.distinct_id)
                    if subscription.created_by
                    else str(subscription.team_id),
                    previous_target_value=None,
                    previous_value=None,
                    invite_message=None,
                    trigger_type=SubscriptionTriggerType.MANUAL,
                    resource_type=subscription.resource_type,
                ),
                id=workflow_id,
                task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            )
        )
    except WorkflowAlreadyStartedError:
        return ManualDeliveryResult(outcome=ManualDeliveryOutcome.ALREADY_RUNNING, workflow_id=workflow_id)
    except Exception as e:
        capture_exception(e)
        return ManualDeliveryResult(outcome=ManualDeliveryOutcome.FAILED, workflow_id=workflow_id)
    return ManualDeliveryResult(outcome=ManualDeliveryOutcome.STARTED, workflow_id=workflow_id)
