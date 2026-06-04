from typing import Any

from django.conf import settings

from rest_framework import serializers

from posthog.helpers.email_utils import (
    contains_bare_domain,
    sanitize_display_name,
    sanitize_message_body,
    validate_display_name,
    validate_message_body,
)

from .models import UserInterviewTopic

INVITE_EMAIL_TEMPLATE = "email/interview_invite.html"

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
    recipient. Re-sanitizes the stored subject/message at render time (defense-in-depth): a stale
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
