from posthog.models.integration import Integration
from posthog.models.team.team import Team

# Firebase identifies an app by its project_id, APNs by its bundle_id. Kept in step with
# _find_integrations in products/messaging/backend/api/push_subscriptions.py, which resolves the same
# mapping in the opposite direction (app_id to integration).
PUSH_APP_ID_CONFIG_KEYS = {"firebase": "project_id", "apns": "bundle_id"}


def build_push_config(team: Team) -> dict:
    """The app_ids this team can accept device registrations for.

    Mobile SDKs register a device token on launch whenever push capture is on, and the registration
    endpoint rejects any app_id with no matching integration. Publishing the configured ids lets an SDK
    skip the request entirely rather than posting a rejection on every process start.

    Always present, including as an empty list. An SDK cannot tell an unconfigured project from an
    older server that never sends the key, so absent has to keep meaning "attempt the registration".
    """
    integrations = Integration.objects.filter(team=team, kind__in=list(PUSH_APP_ID_CONFIG_KEYS)).only("kind", "config")
    # config is a JSONField, so an identifier can be any JSON value. Anything but a non-empty string is
    # unusable as an app_id, and letting one through would raise inside the set or the sort — which
    # aborts build_config and leaves the team's whole remote config stale, not just its push key.
    app_ids = sorted(
        {
            app_id
            for integration in integrations
            if isinstance(app_id := integration.config.get(PUSH_APP_ID_CONFIG_KEYS[integration.kind]), str) and app_id
        }
    )
    return {"appIds": app_ids}
