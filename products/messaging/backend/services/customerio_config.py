from typing import IO, Any

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.integration import Integration

from products.messaging.backend.models.optout_sync_config import OptOutSyncConfig
from products.messaging.backend.services.customerio_import_service import CustomerIOImportService


@frozen
class SavedConfig:
    enabled: bool
    has_credentials: bool


class ConfigConflict(Exception):
    pass


class ConfigIncomplete(Exception):
    pass


def import_from_customerio(team_id: int, app_api_key: str | None, created_by_id: int | None) -> dict[str, Any]:
    integration = Integration.objects.filter(team_id=team_id, kind="customerio-app").first()
    api_key = app_api_key or (integration.sensitive_config.get("app_api_key") if integration else None)

    if not api_key:
        raise ConfigIncomplete("No API key provided and no stored key found.")

    if integration and app_api_key:
        raise ConfigConflict("Integration already exists. Delete it first to use a different key.")

    if not integration:
        integration = Integration.objects.create(
            team_id=team_id,
            kind="customerio-app",
            sensitive_config={"app_api_key": api_key},
            created_by_id=created_by_id,
            errors="",
        )

    config, _ = OptOutSyncConfig.objects.get_or_create(team_id=team_id)
    config.app_integration = integration
    config.save(update_fields=["app_integration"])

    # Run import synchronously
    result = CustomerIOImportService(team_id=team_id, api_key=api_key, created_by_id=created_by_id).import_api_data()

    # Persist import result (success or failure)
    if result.get("status") == "completed":
        config.app_import_result = {
            "status": "completed",
            "imported_at": timezone.now().isoformat(),
            "categories_created": result.get("categories_created", 0),
            "globally_unsubscribed_count": result.get("globally_unsubscribed_count", 0),
        }
    else:
        errors = result.get("errors", [])
        config.app_import_result = {
            "status": "failed",
            "imported_at": timezone.now().isoformat(),
            "error": ", ".join(errors) if errors else "Import failed",
        }
    config.save(update_fields=["app_import_result"])
    return result


def sync_config_state(team_id: int) -> dict[str, Any]:
    try:
        config = OptOutSyncConfig.objects.select_related(
            "app_integration",
            "webhook_integration",
            "track_integration",
        ).get(team_id=team_id)
    except OptOutSyncConfig.DoesNotExist:
        return {
            "app_integration_id": None,
            "app_import_result": None,
            "csv_import_result": None,
            "webhook_enabled": False,
            "has_webhook_secret": False,
            "track_enabled": False,
            "has_track_credentials": False,
        }

    return {
        "app_integration_id": config.app_integration.id if config.app_integration else None,
        "app_import_result": config.app_import_result,
        "csv_import_result": config.csv_import_result,
        "webhook_enabled": config.webhook_enabled,
        "has_webhook_secret": bool(
            config.webhook_integration and config.webhook_integration.sensitive_config.get("webhook_signing_secret")
        ),
        "track_enabled": config.track_enabled,
        "has_track_credentials": bool(
            config.track_integration
            and config.track_integration.sensitive_config.get("site_id")
            and config.track_integration.sensitive_config.get("api_key")
        ),
    }


def remove_app_config(team_id: int) -> None:
    Integration.objects.filter(team_id=team_id, kind="customerio-app").delete()
    try:
        config = OptOutSyncConfig.objects.get(team_id=team_id)
        config.app_integration = None
        config.app_import_result = None
        config.save(update_fields=["app_integration", "app_import_result"])
    except OptOutSyncConfig.DoesNotExist:
        pass


def save_webhook_config(
    team_id: int, signing_secret: str | None, enabled: bool, created_by_id: int | None
) -> SavedConfig:
    integration = Integration.objects.filter(team_id=team_id, kind="customerio-webhook").first()

    if integration and signing_secret:
        raise ConfigConflict("Integration already exists. Delete it first to use a different secret.")

    if enabled and not integration and not signing_secret:
        raise ConfigIncomplete("Webhook signing secret is required to enable sync.")

    if not integration and signing_secret:
        integration = Integration.objects.create(
            team_id=team_id,
            kind="customerio-webhook",
            sensitive_config={"webhook_signing_secret": signing_secret},
            created_by_id=created_by_id,
            errors="",
        )

    config, _ = OptOutSyncConfig.objects.get_or_create(team_id=team_id)
    config.webhook_integration = integration
    config.webhook_enabled = enabled
    config.save(update_fields=["webhook_integration", "webhook_enabled"])

    return SavedConfig(
        enabled=enabled,
        has_credentials=bool(integration and integration.sensitive_config.get("webhook_signing_secret")),
    )


def remove_webhook_config(team_id: int) -> None:
    Integration.objects.filter(team_id=team_id, kind="customerio-webhook").delete()
    try:
        config = OptOutSyncConfig.objects.get(team_id=team_id)
        config.webhook_integration = None
        config.webhook_enabled = False
        config.save(update_fields=["webhook_integration", "webhook_enabled"])
    except OptOutSyncConfig.DoesNotExist:
        pass


def save_track_config(
    team_id: int, site_id: str | None, api_key: str | None, region: str, enabled: bool, created_by_id: int | None
) -> SavedConfig:
    has_new_creds = bool(site_id and api_key)
    integration = Integration.objects.filter(team_id=team_id, kind="customerio-track").first()

    if integration and has_new_creds:
        raise ConfigConflict("Integration already exists. Delete it first to use different credentials.")

    if enabled and not integration and not has_new_creds:
        raise ConfigIncomplete("Site ID and API key are required to enable outbound sync.")

    if not integration and has_new_creds:
        integration = Integration.objects.create(
            team_id=team_id,
            kind="customerio-track",
            sensitive_config={"site_id": site_id, "api_key": api_key},
            config={"region": region},
            created_by_id=created_by_id,
            errors="",
        )

    config, _ = OptOutSyncConfig.objects.get_or_create(team_id=team_id)
    config.track_integration = integration
    config.track_enabled = enabled
    config.save(update_fields=["track_integration", "track_enabled"])

    return SavedConfig(
        enabled=enabled,
        has_credentials=bool(
            integration and integration.sensitive_config.get("site_id") and integration.sensitive_config.get("api_key")
        ),
    )


def remove_track_config(team_id: int) -> None:
    Integration.objects.filter(team_id=team_id, kind="customerio-track").delete()
    try:
        config = OptOutSyncConfig.objects.get(team_id=team_id)
        config.track_integration = None
        config.track_enabled = False
        config.save(update_fields=["track_integration", "track_enabled"])
    except OptOutSyncConfig.DoesNotExist:
        pass


def import_preferences_csv(team_id: int, csv_file: IO[bytes], created_by_id: int | None) -> dict[str, Any]:
    # Process CSV synchronously (should be fast enough for reasonable file sizes)
    result = CustomerIOImportService(
        team_id=team_id, api_key=None, created_by_id=created_by_id
    ).process_preferences_csv(csv_file)

    config, _ = OptOutSyncConfig.objects.get_or_create(team_id=team_id)
    if result.get("status") == "completed":
        config.csv_import_result = {
            "status": "completed",
            "imported_at": timezone.now().isoformat(),
            "total_rows": result.get("total_rows", 0),
            "users_with_optouts": result.get("users_with_optouts", 0),
            "users_skipped": result.get("users_skipped", 0),
            "parse_errors": result.get("parse_errors", 0),
        }
    else:
        config.csv_import_result = {
            "status": "failed",
            "imported_at": timezone.now().isoformat(),
            "error": result.get("details", "CSV import failed"),
        }
    config.save(update_fields=["csv_import_result"])
    return result
