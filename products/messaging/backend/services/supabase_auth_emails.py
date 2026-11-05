"""Supabase auth emails: Supabase's Send Email Hook posts each auth email here, and each one goes out as a
transactional email from the template mapped to its email action type.

The hook is synchronous. Supabase waits for the answer before it finishes the user's sign up or sign in, and gives
up after 5 seconds, so the hook only queues the sends and never waits for delivery. A failed or timed-out hook rolls
the sign up back in Supabase."""

import json
import time
import base64
import binascii
from collections.abc import Mapping
from functools import partial
from typing import Any
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction

import structlog

from posthog.dataclasses import frozen
from posthog.ingress.verify.schemes import VerificationOutcome, standard_webhooks_scheme
from posthog.models.team import Team

from products.messaging.backend.facade.contracts import (
    DeliveryUnavailable,
    IdempotencyKeyInFlight,
    QuotaLimited,
    SupabaseAuthEmailSettings,
    SupabaseAuthEmailSettingsInvalid,
    SupabaseEmailActionType,
    SupabaseHookResult,
    TransactionalEmailError,
)
from products.messaging.backend.models import MessageTemplate, SupabaseAuthEmailConfig
from products.messaging.backend.services.message_templates import create_template
from products.messaging.backend.services.supabase_auth_email_templates import (
    STARTER_TEMPLATES,
    starter_template_content,
)
from products.messaging.backend.services.transactional_email import make_transactional, send_transactional_email

logger = structlog.get_logger(__name__)

MAX_HOOK_BODY_BYTES = 256 * 1024
# The Standard Webhooks spec asks for at least 24 bytes. A shorter key is almost always a truncated paste.
MIN_SECRET_KEY_BYTES = 24
SIGNATURE_TOLERANCE_SECONDS = 5 * 60
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
SEND_FAILED_MESSAGE = "We couldn't send your email. Try again in a few minutes."
# Supabase gives up on the hook after 5 seconds, so every send shares this budget and the answer still arrives.
SEND_BUDGET_SECONDS = 4.0
MIN_SEND_SECONDS = 0.25


def _signing_key(hook_secret: str) -> bytes | None:
    encoded = hook_secret.strip().removeprefix("v1,").removeprefix("whsec_")
    try:
        key = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None
    return key if len(key) >= MIN_SECRET_KEY_BYTES else None


def _normalized_supabase_url(supabase_url: str) -> str:
    url = supabase_url.strip().rstrip("/")
    parts = urlsplit(url)
    # A local Supabase stack serves plain http, which only a development instance can reach anyway.
    local_http = settings.DEBUG and parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS
    if (
        (parts.scheme != "https" and not local_http)
        or not parts.hostname
        or parts.path
        or parts.query
        or parts.fragment
    ):
        raise SupabaseAuthEmailSettingsInvalid(
            "supabase_url", "Enter your Supabase project URL, such as https://abcdefgh.supabase.co."
        )
    return url


def _config(team_id: int) -> SupabaseAuthEmailConfig | None:
    return SupabaseAuthEmailConfig.objects.for_team(team_id).first()


def _settings(config: SupabaseAuthEmailConfig | None) -> SupabaseAuthEmailSettings:
    if config is None:
        return SupabaseAuthEmailSettings(supabase_url="", has_hook_secret=False, templates={})
    return SupabaseAuthEmailSettings(
        supabase_url=config.supabase_url,
        has_hook_secret=bool(config.hook_secret),
        templates={action: UUID(template_id) for action, template_id in config.templates.items()},
    )


def get_settings(team_id: int) -> SupabaseAuthEmailSettings:
    return _settings(_config(team_id))


def _sendable_template_ids(team_id: int, template_ids: set[UUID]) -> set[UUID]:
    # Auth emails carry sign-in codes and reset links, and only a sensitive template keeps them out of stored
    # sends and click tracking.
    return set(
        MessageTemplate.objects.filter(
            team_id=team_id,
            id__in=template_ids,
            deleted=False,
            transactional_hog_flow_id__isnull=False,
            sensitive=True,
        ).values_list("id", flat=True)
    )


def template_workflow_ids(team_id: int, template_ids: set[UUID]) -> set[UUID]:
    """The transactional workflows the given templates send through."""
    workflow_ids = MessageTemplate.objects.filter(
        team_id=team_id, id__in=template_ids, transactional_hog_flow_id__isnull=False
    ).values_list("transactional_hog_flow_id", flat=True)
    return {workflow_id for workflow_id in workflow_ids if workflow_id is not None}


def _check_templates(team_id: int, templates: Mapping[str, UUID]) -> None:
    for action in templates:
        if action not in SupabaseEmailActionType.values:
            raise SupabaseAuthEmailSettingsInvalid("templates", f"{action} isn't a Supabase email type.")
    found = _sendable_template_ids(team_id, set(templates.values()))
    missing = [action for action, template_id in templates.items() if template_id not in found]
    if missing:
        labels = ", ".join(SupabaseEmailActionType(action).label for action in missing)
        raise SupabaseAuthEmailSettingsInvalid(
            "templates",
            f"Pick a transactional template marked sensitive for: {labels}. Sensitive templates keep sign-in codes "
            "and reset links out of stored emails.",
        )


def save_settings(
    team_id: int,
    user_id: int | None,
    *,
    supabase_url: str | None = None,
    hook_secret: str | None = None,
    templates: Mapping[str, UUID] | None = None,
) -> SupabaseAuthEmailSettings:
    """Update the fields that are passed."""
    if supabase_url:
        supabase_url = _normalized_supabase_url(supabase_url)
    if hook_secret and _signing_key(hook_secret) is None:
        raise SupabaseAuthEmailSettingsInvalid(
            "hook_secret", "Paste the full hook secret from Supabase. It starts with v1,whsec_."
        )
    if templates is not None:
        _check_templates(team_id, templates)

    with transaction.atomic():
        config, _ = (
            SupabaseAuthEmailConfig.objects.for_team(team_id)
            .select_for_update()
            .get_or_create(team_id=team_id, defaults={"created_by_id": user_id})
        )
        if supabase_url is not None:
            config.supabase_url = supabase_url
        if hook_secret:
            config.hook_secret = hook_secret.strip()
        if templates is not None:
            config.templates = {action: str(template_id) for action, template_id in templates.items()}
        config.save()
    return _settings(config)


def delete_settings(team_id: int) -> SupabaseAuthEmailSettings:
    """Remove the project URL, hook secret and template mappings, so the hook refuses every call. The templates stay."""
    SupabaseAuthEmailConfig.objects.for_team(team_id).delete()
    return _settings(None)


def create_starter_templates(team_id: int, user_id: int | None) -> SupabaseAuthEmailSettings:
    """Create a transactional template for each core auth email that has none mapped yet, and map it.
    Raises SenderUnavailable when the team has no verified sender."""
    # One transaction, so a missing sender leaves no half-made templates behind.
    with transaction.atomic():
        # Locks the config first, so two concurrent calls can't both create a full set of templates.
        SupabaseAuthEmailConfig.objects.for_team(team_id).select_for_update().get_or_create(
            team_id=team_id, defaults={"created_by_id": user_id}
        )
        mapped = get_settings(team_id).templates
        # A mapping whose template was deleted or stopped being transactional counts as unmapped, so it gets a
        # starter template instead of failing the whole call.
        sendable = _sendable_template_ids(team_id, set(mapped.values()))
        templates = {action: template_id for action, template_id in mapped.items() if template_id in sendable}
        for action, starter in STARTER_TEMPLATES.items():
            if action in templates:
                continue
            template = create_template(
                team_id,
                user_id,
                {
                    "name": starter.name,
                    "type": "email",
                    "content": starter_template_content(starter),
                    "sensitive": True,
                },
            )
            make_transactional(team_id, template.id, user_id=user_id, from_integration_id=None)
            templates[action] = template.id
        return save_settings(team_id, user_id, templates=templates)


@frozen
class _HookUser:
    id: str
    email: str
    new_email: str
    user_metadata: dict[str, Any]


@frozen
class _HookEmailData:
    # Supabase keeps this id when it retries, but gives every attempt a new `webhook-id`.
    request_id: str
    email_action_type: str
    token: str
    token_hash: str
    token_new: str
    token_hash_new: str
    redirect_to: str
    # The address a user changed away from, set on the email-changed notification.
    old_email: str


@frozen
class _Send:
    to: str
    token: str
    token_hash: str


def _str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    return value if isinstance(value, str) else ""


def _parse_payload(body: bytes) -> tuple[_HookUser, _HookEmailData] | None:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    user, email_data, request_metadata = payload.get("user"), payload.get("email_data"), payload.get("metadata")
    if not isinstance(user, dict) or not isinstance(email_data, dict) or not isinstance(request_metadata, dict):
        return None
    metadata = user.get("user_metadata")
    hook_user = _HookUser(
        id=_str(user, "id"),
        email=_str(user, "email"),
        new_email=_str(user, "new_email"),
        user_metadata=metadata if isinstance(metadata, dict) else {},
    )
    hook_email_data = _HookEmailData(
        request_id=_str(request_metadata, "uuid"),
        email_action_type=_str(email_data, "email_action_type"),
        token=_str(email_data, "token"),
        token_hash=_str(email_data, "token_hash"),
        token_new=_str(email_data, "token_new"),
        token_hash_new=_str(email_data, "token_hash_new"),
        redirect_to=_str(email_data, "redirect_to"),
        old_email=_str(email_data, "old_email"),
    )
    # A phone-only user adding an email address has no current address yet, only the new one.
    has_recipient = bool(hook_user.email or hook_user.new_email)
    if not hook_email_data.request_id or not hook_user.id or not has_recipient or not hook_email_data.email_action_type:
        return None
    return hook_user, hook_email_data


def _sends(user: _HookUser, data: _HookEmailData) -> list[_Send]:
    if data.email_action_type == SupabaseEmailActionType.EMAIL_CHANGED_NOTIFICATION:
        # The alert has to reach the address that was replaced, in case the change was not the owner's.
        return [_Send(to=data.old_email or user.email, token=data.token, token_hash=data.token_hash)]
    if data.email_action_type != SupabaseEmailActionType.EMAIL_CHANGE:
        return [_Send(to=user.email or user.new_email, token=data.token, token_hash=data.token_hash)]
    if data.token_hash_new and not user.email:
        # Only the new address exists, so it gets its own pair: `token_new` with the plain hash.
        return [_Send(to=user.new_email, token=data.token_new, token_hash=data.token_hash)]
    if data.token_hash_new:
        # Secure email change sends one email to each address. Supabase keeps the old field names, so the
        # current address gets the `_new` hash and the new address gets the plain one.
        return [
            _Send(to=user.email, token=data.token, token_hash=data.token_hash_new),
            _Send(to=user.new_email or user.email, token=data.token_new, token_hash=data.token_hash),
        ]
    return [
        _Send(
            to=user.new_email or user.email,
            token=data.token or data.token_new,
            token_hash=data.token_hash or data.token_hash_new,
        )
    ]


def _confirmation_url(supabase_url: str, data: _HookEmailData, token_hash: str) -> str:
    # Reauthentication has no verify link. The user types the code instead.
    if not token_hash or data.email_action_type == SupabaseEmailActionType.REAUTHENTICATION:
        return ""
    query = urlencode({"token": token_hash, "type": data.email_action_type, "redirect_to": data.redirect_to})
    return f"{supabase_url}/auth/v1/verify?{query}"


def _message_data(config: SupabaseAuthEmailConfig, user: _HookUser, data: _HookEmailData, send: _Send) -> dict:
    return {
        "email_action_type": data.email_action_type,
        "confirmation_url": _confirmation_url(config.supabase_url, data, send.token_hash),
        "token": send.token,
        "token_hash": send.token_hash,
        "redirect_to": data.redirect_to,
        "email": user.email,
        "new_email": user.new_email,
        "user_metadata": user.user_metadata,
    }


def _verified(config: SupabaseAuthEmailConfig, body: bytes, headers: Mapping[str, str]) -> bool:
    signing_key = _signing_key(config.hook_secret or "")
    if signing_key is None:
        return False
    scheme = standard_webhooks_scheme(lambda: signing_key, tolerance_seconds=SIGNATURE_TOLERANCE_SECONDS)
    return scheme.verify(body=body, headers=headers).outcome == VerificationOutcome.VERIFIED


def handle_send_email_hook(team: Team, body: bytes, headers: Mapping[str, str]) -> SupabaseHookResult:
    deadline = time.monotonic() + SEND_BUDGET_SECONDS
    config = _config(team.id)
    if config is None or not config.hook_secret or not _verified(config, body, headers):
        return SupabaseHookResult(status=401, message="The hook signature doesn't match. Check the hook secret.")

    parsed = _parse_payload(body)
    if parsed is None:
        return SupabaseHookResult(status=400, message="The hook payload isn't a Send Email Hook payload.")
    user, data = parsed

    action = data.email_action_type
    result = partial(SupabaseHookResult, email_action_type=action)
    # Confirmation links point at the project's verify endpoint, so without the URL every link would be broken.
    if not config.supabase_url:
        return result(status=400, message=SEND_FAILED_MESSAGE, error_code="project_url_missing")
    template_id = config.templates.get(action)
    if template_id is None:
        # A missing notification only loses a heads-up, so it must not fail the user's request. A missing auth
        # email would leave the user without their link or code, so Supabase has to show the failure.
        if action.endswith("_notification"):
            return result(status=200, skipped=True)
        return result(status=400, message=f"No PostHog template is set for the {action} email.")
    # The template can change after it was mapped. A send through one that is no longer sensitive would store
    # sign-in codes and reset links.
    if UUID(template_id) not in _sendable_template_ids(team.id, {UUID(template_id)}):
        logger.warning("supabase_auth_email_template_not_sendable", team_id=team.id, email_action_type=action)
        return result(status=400, message=SEND_FAILED_MESSAGE, error_code="template_not_sendable")

    sends = _sends(user, data)
    for index, send in enumerate(sends):
        remaining = deadline - time.monotonic()
        if remaining < MIN_SEND_SECONDS:
            return result(status=503, message=SEND_FAILED_MESSAGE, error_code="deadline_exceeded", sent_count=index)
        try:
            send_transactional_email(
                team,
                UUID(template_id),
                to=send.to,
                distinct_id=user.id,
                message_data=_message_data(config, user, data, send),
                # A retry of the same request never sends an email twice, even when only one of two sends failed.
                idempotency_key=f"supabase-{data.request_id}-{index}"[:255],
                timeout=remaining,
            )
        # Supabase shows `message` to the person signing in, so it never carries the setup advice the errors hold.
        except (QuotaLimited, IdempotencyKeyInFlight) as e:
            return result(status=429, message=SEND_FAILED_MESSAGE, error_code=e.code, sent_count=index)
        except TransactionalEmailError as e:
            logger.warning("supabase_auth_email_rejected", team_id=team.id, error_code=e.code)
            return result(status=400, message=SEND_FAILED_MESSAGE, error_code=e.code, sent_count=index)
        except ObjectDoesNotExist:
            # The mapped template was deleted after it was mapped.
            logger.warning("supabase_auth_email_template_missing", team_id=team.id, email_action_type=action)
            return result(status=400, message=SEND_FAILED_MESSAGE, error_code="template_missing", sent_count=index)
        except DeliveryUnavailable:
            return result(status=503, message=SEND_FAILED_MESSAGE, error_code="delivery_unavailable", sent_count=index)
    return result(status=200, sent_count=len(sends))
