from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_http_methods

import structlog

from posthog.api.capture import capture_internal
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.plugins.plugin_server_api import validate_messaging_preferences_token

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    EMAIL_TRACKING_PREFERENCE_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)
from products.messaging.backend.services.customerio_sync_service import sync_preferences_to_customerio
from products.workflows.backend.facade.enums import EmailTrackingConsentMode

logger = structlog.get_logger(__name__)


def report_workflows_email_unsubscribed(team_id: int, identifier: str, category_ids: list[str], source: str) -> None:
    """
    Emit $workflows_email_unsubscribed engagement events into the customer's project.

    Mirrors the plugin-server's $workflows_email_* engagement events (email-tracking.service.ts),
    gated on the same capture_workflows_engagement_events team flag. The unsubscribe token only
    carries team_id + identifier, so this event is email-level: distinct_id is the recipient's
    email, and no workflow/action id is available. Best-effort — never fails the unsubscribe flow.
    """
    try:
        team = Team.objects.get(id=team_id)
        if not team.workflows_config.capture_workflows_engagement_events:
            return

        # The form POST accepts arbitrary category id strings; only emit for the team's real
        # categories (or "$all") so a token bearer can't inject junk property values
        known_category_ids: set[str] = set()
        if any(category_id != ALL_MESSAGE_PREFERENCE_CATEGORY_ID for category_id in category_ids):
            known_category_ids = {
                str(category_id)
                for category_id in MessageCategory.objects.filter(team_id=team_id, deleted=False).values_list(
                    "id", flat=True
                )
            }
    except Exception as e:
        capture_exception(e)
        return

    # Each category is independently best-effort: one failed capture must not skip the rest
    for category_id in category_ids:
        if category_id != ALL_MESSAGE_PREFERENCE_CATEGORY_ID and category_id not in known_category_ids:
            continue
        properties: dict[str, Any] = {
            "$email": identifier,
            "category": category_id,
            "source": source,
        }
        try:
            result = capture_internal(
                token=team.api_token,
                event_name="$workflows_email_unsubscribed",
                event_source="workflows_unsubscribe",
                distinct_id=identifier,
                properties=properties,
            )
            if not result.succeeded():
                logger.error(
                    "workflows_email_unsubscribed_capture_failed",
                    team_id=team_id,
                    category=category_id,
                    error=result.error,
                )
        except Exception as e:
            capture_exception(e)


def report_workflows_email_tracking_consent_updated(team_id: int, identifier: str, status: str) -> None:
    """
    Emit a $workflows_email_tracking_consent_updated engagement event when a recipient
    changes their open/click tracking consent on the preferences page. Gated on the same
    capture_workflows_engagement_events flag as the other $workflows_email_* events.
    Best-effort — never fails the preferences flow.
    """
    try:
        team = Team.objects.get(id=team_id)
        if not team.workflows_config.capture_workflows_engagement_events:
            return
        result = capture_internal(
            token=team.api_token,
            event_name="$workflows_email_tracking_consent_updated",
            event_source="workflows_preferences",
            distinct_id=identifier,
            properties={"$email": identifier, "status": status, "source": "preferences_page"},
        )
        if not result.succeeded():
            logger.error(
                "workflows_email_tracking_consent_capture_failed",
                team_id=team_id,
                error=result.error,
            )
    except Exception as e:
        capture_exception(e)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def preferences_page(request: HttpRequest, token: str) -> HttpResponse:
    """Render the preferences page for a given recipient token"""
    response = validate_messaging_preferences_token(token)
    if response.status_code != 200:
        error_msg = response.json().get("error", "Invalid recipient token")
        return render(request, "message_preferences/error.html", {"error": error_msg}, status=400)

    data = response.json()
    if not data.get("valid"):
        return render(request, "message_preferences/error.html", {"error": "Invalid recipient token"}, status=400)

    team_id = data.get("team_id")
    identifier = data.get("identifier")
    if not team_id or not identifier:
        return render(request, "message_preferences/error.html", {"error": "Invalid recipient"}, status=400)

    recipient, _ = MessageRecipientPreference.objects.get_or_create(team_id=team_id, identifier=identifier)
    categories = MessageCategory.objects.filter(deleted=False, team=team_id, category_type="marketing").order_by("name")

    is_one_click_unsubscribe = (
        request.GET.get("one_click_unsubscribe") == "1" or request.POST.get("one_click_unsubscribe") == "1"
    )
    if is_one_click_unsubscribe:
        was_fully_opted_out = recipient.get_preference(ALL_MESSAGE_PREFERENCE_CATEGORY_ID) == PreferenceStatus.OPTED_OUT

        # If one-click unsubscribe, set all preferences to opted out
        preferences_dict = {str(cat.id): PreferenceStatus.OPTED_OUT.value for cat in categories}

        # Also set the "$all" preference
        preferences_dict[ALL_MESSAGE_PREFERENCE_CATEGORY_ID] = PreferenceStatus.OPTED_OUT.value

        # Unsubscribing is about which emails arrive, not how they're measured — a stored
        # tracking-consent answer must survive the wholesale rebuild
        tracking_pref = (recipient.preferences or {}).get(EMAIL_TRACKING_PREFERENCE_ID)
        if tracking_pref is not None:
            preferences_dict[EMAIL_TRACKING_PREFERENCE_ID] = tracking_pref

        recipient.preferences = preferences_dict
        recipient.save(update_fields=["preferences"])

        sync_preferences_to_customerio(team_id, identifier, preferences_dict)

        # Only a genuine transition emits, so token replays and scanner prefetches don't inflate events
        if not was_fully_opted_out:
            report_workflows_email_unsubscribed(team_id, identifier, [ALL_MESSAGE_PREFERENCE_CATEGORY_ID], "one_click")

        if request.method == "POST":
            return HttpResponse(status=200)

    # Only fetch active categories and their preferences
    preferences = recipient.get_all_preferences() if recipient else {}

    categories_templating = [
        {
            "id": cat.id,
            "name": cat.name,
            "description": cat.public_description,
            "status": preferences.get(str(cat.id), PreferenceStatus.NO_PREFERENCE),
        }
        for cat in categories
    ]

    # Only surface the tracking-consent toggle when the team actually enforces consent —
    # in "off" mode a stored preference would have no effect on sends
    tracking_consent_mode = Team.objects.get(id=team_id).workflows_config.email_tracking_consent_mode
    tracking_status = preferences.get(EMAIL_TRACKING_PREFERENCE_ID, PreferenceStatus.NO_PREFERENCE)

    context = {
        "recipient": recipient,
        "categories": [
            *categories_templating,
            {
                "id": ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
                "name": "All marketing communications",
                "description": "Unsubscribing here overrides individual preferences.",
                "status": preferences.get(ALL_MESSAGE_PREFERENCE_CATEGORY_ID, PreferenceStatus.NO_PREFERENCE),
            },
        ],
        "token": token,
        "email_tracking_consent_enabled": tracking_consent_mode != EmailTrackingConsentMode.OFF,
        # No stored answer falls back to the mode's default: tracked under opt-out, untracked under opt-in
        "email_tracking_allowed": (
            tracking_status == PreferenceStatus.OPTED_IN
            if tracking_consent_mode == EmailTrackingConsentMode.OPT_IN
            else tracking_status != PreferenceStatus.OPTED_OUT
        ),
    }

    return render(
        request,
        "message_preferences/one_click_unsubscribe_success.html"
        if is_one_click_unsubscribe
        else "message_preferences/preferences.html",
        context,
    )


@csrf_protect
@require_http_methods(["POST"])
def update_preferences(request: HttpRequest) -> JsonResponse:
    """Update preferences for a recipient"""
    token = request.POST.get("token")
    if not token:
        return JsonResponse({"error": "Missing token"}, status=400)

    response = validate_messaging_preferences_token(token)
    if response.status_code != 200:
        error_msg = response.json().get("error", "Invalid recipient token")
        return JsonResponse({"error": error_msg}, status=400)

    data = response.json()
    if not data.get("valid"):
        return JsonResponse({"error": "Invalid recipient token"}, status=400)
    team_id = data.get("team_id")
    identifier = data.get("identifier")
    if not team_id or not identifier:
        return JsonResponse({"error": "Invalid recipient"}, status=400)

    recipient = None

    try:
        recipient = MessageRecipientPreference.objects.get(team_id=team_id, identifier=identifier)
    except MessageRecipientPreference.DoesNotExist:
        recipient = MessageRecipientPreference(team_id=team_id, identifier=identifier)

    try:
        prior_preferences = dict(recipient.preferences or {})
        preferences = request.POST.getlist("preferences[]")
        # Convert to dict of category_id: status
        preferences_dict = {}

        for pref in preferences:
            category_id, opted_in = pref.split(":")

            if opted_in not in ["true", "false"]:
                return JsonResponse({"error": "Preference values must be 'true' or 'false'"}, status=400)

            status = PreferenceStatus.OPTED_IN if opted_in == "true" else PreferenceStatus.OPTED_OUT
            preferences_dict[category_id] = status.value

        # $email_tracking is a measurement consent, not a subscription — it must neither
        # block nor trigger the "unsubscribed from everything" $all computation
        subscription_prefs = {k: v for k, v in preferences_dict.items() if k != EMAIL_TRACKING_PREFERENCE_ID}

        # If all preferences are opted out, add the "$all" preference
        if subscription_prefs and all(v == PreferenceStatus.OPTED_OUT.value for v in subscription_prefs.values()):
            preferences_dict[ALL_MESSAGE_PREFERENCE_CATEGORY_ID] = PreferenceStatus.OPTED_OUT.value

        # A save that doesn't include the tracking toggle (e.g. consent mode is off) must
        # not erase a stored consent answer in the wholesale rebuild
        if EMAIL_TRACKING_PREFERENCE_ID not in preferences_dict and EMAIL_TRACKING_PREFERENCE_ID in prior_preferences:
            preferences_dict[EMAIL_TRACKING_PREFERENCE_ID] = prior_preferences[EMAIL_TRACKING_PREFERENCE_ID]

        # A tracking-only save (no category toggles rendered, e.g. a team without marketing
        # categories) must not rebuild subscription state - it would drop a stored $all opt-out
        if not subscription_prefs:
            preferences_dict = {**prior_preferences, **preferences_dict}

        # Update all preferences with a single DB write
        recipient.preferences = preferences_dict
        recipient.save()

        sync_preferences_to_customerio(team_id, identifier, preferences_dict)

        # Only genuine opt-out transitions count, so repeated saves don't double-emit
        newly_opted_out = [
            category_id
            for category_id, status in preferences_dict.items()
            if category_id != EMAIL_TRACKING_PREFERENCE_ID
            and status == PreferenceStatus.OPTED_OUT.value
            and prior_preferences.get(category_id) != PreferenceStatus.OPTED_OUT.value
        ]
        if newly_opted_out:
            report_workflows_email_unsubscribed(team_id, identifier, newly_opted_out, "preferences_page")

        new_tracking_consent = preferences_dict.get(EMAIL_TRACKING_PREFERENCE_ID)
        if new_tracking_consent is not None and new_tracking_consent != prior_preferences.get(
            EMAIL_TRACKING_PREFERENCE_ID
        ):
            report_workflows_email_tracking_consent_updated(team_id, identifier, new_tracking_consent)

        return JsonResponse({"success": True})

    except Exception as e:
        capture_exception(e)
        return JsonResponse({"error": "Failed to update preferences"}, status=400)
