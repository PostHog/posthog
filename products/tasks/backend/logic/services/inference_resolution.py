"""Decide who pays for the model use of a run, and hand a run the credential it selected.

``resolve_inference`` runs when a run is created. It reads what the user has stored and returns
the run state keys that pin the choice. ``issue_run_claude_subscription`` runs when the agent in
the sandbox asks for the secret. No secret enters run state, a workflow input, or a log line.
"""

from collections.abc import Mapping
from dataclasses import field
from typing import Literal, cast

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum
from posthog.exceptions_capture import capture_exception
from posthog.models.integration.claude_subscription import ClaudeSubscriptionStore, claude_subscription_storage_enabled
from posthog.models.integration.codex import CodexUserIntegration
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.constants import CODEX_OWN_SUBSCRIPTION_CLOUD_FEATURE_FLAG
from products.tasks.backend.logic.model_access import (
    CLAUDE_SUBSCRIPTION_SOURCE_STATE_KEY,
    INFERENCE_STATE_KEYS,
    InferenceBilling,
    RunCredentialKind,
    SubscriptionAdapter,
    resolve_model_access,
)

InferenceRequest = Literal["auto", "own_subscription", "posthog"]
InferenceUnavailableCode = Literal["no_user", "credential_missing", "not_available"]


# Each label repeats its value, because the API documents these choices as plain values.
class RunInferenceCredential(LabeledStrEnum):
    CODEX = "codex", "codex"
    CLAUDE_SUBSCRIPTION = "claude_subscription", "claude_subscription"


@frozen
class InferenceDecision:
    mode: InferenceBilling
    adapter: SubscriptionAdapter
    credential_kind: RunCredentialKind | None
    owner_user_id: int | None
    # The protected run state keys to stamp on the run. Never a secret.
    run_state_updates: Mapping[str, object]
    resolved_from_auto: bool


class InferenceUnavailable(Exception):
    """The requested inference mode cannot be used. ``detail`` is safe to show to the user."""

    def __init__(self, detail: str, *, code: InferenceUnavailableCode) -> None:
        self.detail = detail
        self.code = code
        super().__init__(detail)


class InvalidInferenceState(ValueError):
    pass


@frozen
class ClaudeSubscriptionGrant:
    secret: str = field(repr=False)


class ClaudeSubscriptionMissing(Exception):
    """The run uses the stored Claude subscription, but the owner has no usable stored token."""


def resolve_inference(
    *, user_id: int | None, team_id: int, runtime_adapter: str, requested: InferenceRequest
) -> InferenceDecision:
    """Select the inference mode of a new run for ``user_id``.

    ``auto`` prefers the user's subscription for the adapter, then the PostHog gateway. An
    explicit ``own_subscription`` that cannot be used raises ``InferenceUnavailable``. It never
    becomes a gateway run, because that would spend PostHog credits that the user did not select.
    """
    if runtime_adapter not in ("claude", "codex"):
        raise ValueError(f"Unknown runtime adapter {runtime_adapter!r}")
    adapter = cast(SubscriptionAdapter, runtime_adapter)
    from_auto = requested == "auto"
    if requested == "posthog":
        return _posthog_decision(adapter, resolved_from_auto=False)

    team = Team.objects.get(id=team_id)
    user = team.all_users_with_access().filter(id=user_id).first() if user_id is not None else None
    if user is None:
        if from_auto:
            return _posthog_decision(adapter, resolved_from_auto=True)
        raise InferenceUnavailable("A run with no user can only use PostHog credits for model usage.", code="no_user")

    subscription_error = _subscription_unavailable(adapter, user, team)
    if subscription_error is None:
        updates: dict[str, object] = {f"{adapter}_model_access": "own-subscription"}
        if adapter == "claude":
            updates[CLAUDE_SUBSCRIPTION_SOURCE_STATE_KEY] = "server"
        return InferenceDecision(
            mode="own_subscription",
            adapter=adapter,
            credential_kind="claude_subscription" if adapter == "claude" else "codex",
            owner_user_id=user.id,
            run_state_updates=updates,
            resolved_from_auto=from_auto,
        )
    if requested == "own_subscription":
        raise subscription_error
    return _posthog_decision(adapter, resolved_from_auto=True)


def validated_inference_state(inference_state: Mapping[str, object] | None) -> dict[str, object]:
    """The complete inference keys to stamp on a run, from an ``InferenceDecision.run_state_updates``.

    Each key of ``INFERENCE_STATE_KEYS`` gets a value. An absent key gets its gateway default, so
    that a resumed run does not keep the selection of the run before it. Raises
    ``InvalidInferenceState`` for a key that is not an inference key and for an unknown value.
    """
    updates = dict(inference_state or {})
    unknown = sorted(set(updates) - INFERENCE_STATE_KEYS)
    if unknown:
        raise InvalidInferenceState(f"Not an inference state key: {', '.join(unknown)}")
    state: dict[str, object] = {
        "claude_model_access": updates.get("claude_model_access", "posthog-gateway"),
        "codex_model_access": updates.get("codex_model_access", "posthog-gateway"),
        CLAUDE_SUBSCRIPTION_SOURCE_STATE_KEY: updates.get(CLAUDE_SUBSCRIPTION_SOURCE_STATE_KEY, "relay"),
    }
    for adapter in ("claude", "codex"):
        if state[f"{adapter}_model_access"] not in ("posthog-gateway", "own-subscription"):
            raise InvalidInferenceState(f"Unknown {adapter}_model_access value")
    if state[CLAUDE_SUBSCRIPTION_SOURCE_STATE_KEY] not in ("relay", "server"):
        raise InvalidInferenceState(f"Unknown {CLAUDE_SUBSCRIPTION_SOURCE_STATE_KEY} value")
    return state


def issue_run_claude_subscription(state: Mapping[str, object], *, team_id: int) -> ClaudeSubscriptionGrant | None:
    """The stored Claude subscription token of the owner of the run with this state.

    None when the state does not select the stored token, so a gateway run, a Codex run, and a
    run with a relayed token get nothing. Raises ``ClaudeSubscriptionMissing`` when the run
    selected it and the owner has no usable stored token.
    """
    try:
        model_access = resolve_model_access(state)
    except ValueError:
        return None
    if not model_access.uses_stored_claude_subscription or model_access.owner_id is None:
        return None
    team = Team.objects.get(id=team_id)
    owner = team.all_users_with_access().filter(id=model_access.owner_id).first()
    if owner is None or not claude_subscription_storage_enabled(owner, team.organization_id):
        raise ClaudeSubscriptionMissing()
    secret = ClaudeSubscriptionStore.resolve_secret(owner.id)
    if secret is None:
        raise ClaudeSubscriptionMissing()
    return ClaudeSubscriptionGrant(secret=secret)


def _posthog_decision(adapter: SubscriptionAdapter, *, resolved_from_auto: bool) -> InferenceDecision:
    return InferenceDecision(
        mode="posthog",
        adapter=adapter,
        credential_kind=None,
        owner_user_id=None,
        run_state_updates={},
        resolved_from_auto=resolved_from_auto,
    )


def _subscription_unavailable(adapter: SubscriptionAdapter, user: User, team: Team) -> InferenceUnavailable | None:
    if adapter == "claude":
        if not claude_subscription_storage_enabled(user, team.organization_id):
            return InferenceUnavailable(
                "Claude subscriptions are not available for cloud agents in your organization.",
                code="not_available",
            )
        if not ClaudeSubscriptionStore.has(user.id):
            return InferenceUnavailable(
                "Connect your Claude subscription in Cloud agents settings to use it for this run.",
                code="credential_missing",
            )
        return None
    if not _codex_subscription_enabled(user, team):
        return InferenceUnavailable(
            "ChatGPT subscriptions are not available for cloud runs in your organization.", code="not_available"
        )
    integration = CodexUserIntegration.for_user(user.id)
    if integration is None or not integration.is_connected():
        return InferenceUnavailable(
            "Connect your ChatGPT account in ChatGPT subscription settings to use it for this run.",
            code="credential_missing",
        )
    return None


def _codex_subscription_enabled(user: User, team: Team) -> bool:
    organization_id = str(team.organization_id)
    try:
        return bool(
            user.distinct_id
            and posthoganalytics.feature_enabled(
                CODEX_OWN_SUBSCRIPTION_CLOUD_FEATURE_FLAG,
                distinct_id=str(user.distinct_id),
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as error:
        capture_exception(error)
        return False
