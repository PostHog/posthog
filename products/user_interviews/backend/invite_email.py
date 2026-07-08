from typing import Any

from django.conf import settings
from django.template.loader import get_template

from rest_framework import serializers

from posthog.email import inline_css
from posthog.helpers.email_utils import (
    contains_bare_domain,
    sanitize_display_name,
    sanitize_message_body,
    validate_display_name,
    validate_message_body,
)
from posthog.utils import absolute_uri

from .logic import parse_interviewee_identifier
from .models import UserInterviewTopic

INVITE_EMAIL_TEMPLATE = "email/interview_invite.html"
PREVIEW_PLACEHOLDER_PATH = "/interview/preview"

# Interview invite copy is stricter than org-invite copy: we reject bare domains (on top of the
# URL-scheme / bracket / control-char checks the shared validators already enforce) because there's
# no legitimate reason to link out from a research invite, and mail clients auto-link bare domains —
# a phishing vector in a PostHog-branded email.
_INVITE_DOMAIN_ERROR = "Links and domain names aren't allowed in interview invite copy."


def validate_invite_subject(value: str | None) -> str | None:
    validated = validate_display_name(value)
    if contains_bare_domain(validated):
        raise serializers.ValidationError(_INVITE_DOMAIN_ERROR, code="invalid_domain")
    return validated


def validate_invite_message(value: str | None) -> str | None:
    validated = validate_message_body(value)
    if contains_bare_domain(validated):
        raise serializers.ValidationError(_INVITE_DOMAIN_ERROR, code="invalid_domain")
    return validated


def build_invite_email_context(
    *,
    topic: UserInterviewTopic,
    user_name: str,
    interview_url: str,
    subject_override: str = "",
) -> dict[str, Any]:
    """Resolve the subject + template context for a topic's invite email, personalized for one
    recipient. Shared by the send path and the (side-effect-free) preview path so both render
    identically. Re-sanitizes the stored subject/message at render time (defense-in-depth): a stale
    or pre-validation value degrades to the default rather than emitting anything unsafe.
    """
    topic_label = topic.topic or "a quick research interview"
    default_subject = f"Got 5 minutes to talk about {topic_label}?"
    log_context = {"feature": "user_interview_invite", "topic_id": str(topic.id)}
    subject = sanitize_display_name(
        subject_override or topic.invite_subject,
        fallback=default_subject,
        context={**log_context, "field": "subject"},
    )
    invite_message = sanitize_message_body(
        topic.invite_message,
        fallback="",
        context={**log_context, "field": "invite_message"},
    )
    return {
        "subject": subject,
        "template_context": {
            "user_name": user_name,
            "topic": topic_label,
            "interview_url": interview_url,
            "invite_message": invite_message,
            "site_url": settings.SITE_URL,
        },
    }


def render_invite_email_html(
    *,
    topic: UserInterviewTopic,
    user_name: str,
    interview_url: str,
    subject_override: str = "",
) -> dict[str, str]:
    """Render the invite email to CSS-inlined HTML without sending. Renders a fixed template file
    with autoescaped context — user content never reaches the template engine as a template.
    """
    built = build_invite_email_context(
        topic=topic,
        user_name=user_name,
        interview_url=interview_url,
        subject_override=subject_override,
    )
    html = inline_css(get_template(INVITE_EMAIL_TEMPLATE).render(built["template_context"]))
    return {"subject": built["subject"], "html": html}


def _targeted_identifiers(topic: UserInterviewTopic) -> list[str]:
    return [
        raw.strip()
        for raw in [*(topic.interviewee_emails or []), *(topic.interviewee_distinct_ids or [])]
        if raw and raw.strip()
    ]


def resolve_invite_preview(
    *,
    topic: UserInterviewTopic,
    interviewee_identifier: str = "",
) -> dict[str, Any] | None:
    """Render an invite-email preview for one targeted interviewee. Defaults to the first targeted
    interviewee when none is given. Returns None when the topic targets nobody, or when a specific
    interviewee_identifier is given that the topic does not target.

    Read-only and never exposes a live interview link: the previewed body always shows an illustrative
    placeholder URL. The real per-recipient share token is minted only when invites are actually sent,
    so a read-scoped caller can't harvest working interview links through the preview.
    """
    targets = _targeted_identifiers(topic)
    requested = (interviewee_identifier or "").strip()
    identifier = requested or (targets[0] if targets else "")
    if not identifier or (requested and requested not in targets):
        return None

    identity = parse_interviewee_identifier(identifier)
    interview_url = absolute_uri(PREVIEW_PLACEHOLDER_PATH)
    rendered = render_invite_email_html(topic=topic, user_name=identity.display_name, interview_url=interview_url)
    return {
        "interviewee_identifier": identifier,
        "user_name": identity.display_name,
        "email": identity.email,
        "subject": rendered["subject"],
        "html": rendered["html"],
        "interview_url": interview_url,
        "emailable": identity.email is not None,
        "is_preview_link": True,
    }
