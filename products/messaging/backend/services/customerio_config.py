from typing import IO, Any

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager, IntegrationNotFound, IntegrationReader, IntegrationRecord

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


def resolve_app_api_key(team_id: int, app_api_key: str | None) -> str:
    """The App API key to import with: the one sent, or the stored one when none is sent."""
    integration = IntegrationManager.customerio_app.token.find(team_id)
    api_key = app_api_key or (integration.sensitive_config.get("app_api_key") if integration else None)

    if not api_key:
        raise ConfigIncomplete("No API key provided and no stored key found.")

    if integration and app_api_key:
        raise ConfigConflict("Integration already exists. Delete it first to use a different key.")

    return api_key


def save_app_integration(team_id: int, api_key: str, created_by_id: int | None) -> IntegrationRecord:
    """Store the App API key on first use and link it to the sync config. Returns the stored integration."""
    integration = IntegrationManager.customerio_app.token.find(team_id)
    if not integration:
        integration = IntegrationManager.customerio_app.token.create(
            team_id,
            external_id=None,
            config={},
            sensitive_config={"app_api_key": api_key},
            created_by_id=created_by_id,
        )

    config, _ = OptOutSyncConfig.objects.get_or_create(team_id=team_id)
    config.app_integration_id = integration.id
    config.save(update_fields=["app_integration"])
    return integration


def stored_app_api_key(team_id: int, integration_id: int) -> str | None:
    try:
        integration = IntegrationManager.customerio_app.token.get(team_id, integration_id)
    except IntegrationNotFound:
        return None
    return integration.sensitive_config.get("app_api_key")


def import_from_customerio(team_id: int, app_api_key: str | None, created_by_id: int | None) -> dict[str, Any]:
    api_key = resolve_app_api_key(team_id, app_api_key)
    save_app_integration(team_id, api_key, created_by_id)
    config = OptOutSyncConfig.objects.get(team_id=team_id)

    # Run import synchronously
    result = CustomerIOImportService(team_id=team_id, api_key=api_key, created_by_id=created_by_id).import_api_data()

    # Persist import result (success or failure)
    if result.get("status") == "completed":
        config.app_import_result = {
            "status": "completed",
            "imported_at": timezone.now().isoformat(),
            "categories_created": result.get("categories_created", 0),
            "globally_unsubscribed_count": result.get("globally_unsubscribed_count", 0),
            "suppressions_imported": result.get("suppressions_imported", 0),
            "errors": result.get("errors", []),
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


def _delete_integrations(accessor: IntegrationReader, team_id: int) -> None:
    for integration in accessor.list(team_id):
        accessor.delete(team_id, integration.id, ignore_usages=True)


def remove_app_config(team_id: int) -> None:
    _delete_integrations(IntegrationManager.customerio_app.any, team_id)
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
    integration = IntegrationManager.customerio_webhook.token.find(team_id)

    if integration and signing_secret:
        raise ConfigConflict("Integration already exists. Delete it first to use a different secret.")

    if enabled and not integration and not signing_secret:
        raise ConfigIncomplete("Webhook signing secret is required to enable sync.")

    if not integration and signing_secret:
        integration = IntegrationManager.customerio_webhook.token.create(
            team_id,
            external_id=None,
            config={},
            sensitive_config={"webhook_signing_secret": signing_secret},
            created_by_id=created_by_id,
        )

    config, _ = OptOutSyncConfig.objects.get_or_create(team_id=team_id)
    config.webhook_integration_id = integration.id if integration else None
    config.webhook_enabled = enabled
    config.save(update_fields=["webhook_integration", "webhook_enabled"])

    return SavedConfig(
        enabled=enabled,
        has_credentials=bool(integration and integration.sensitive_config.get("webhook_signing_secret")),
    )


def remove_webhook_config(team_id: int) -> None:
    _delete_integrations(IntegrationManager.customerio_webhook.any, team_id)
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
    integration = IntegrationManager.customerio_track.token.find(team_id)

    if integration and has_new_creds:
        raise ConfigConflict("Integration already exists. Delete it first to use different credentials.")

    if enabled and not integration and not has_new_creds:
        raise ConfigIncomplete("Site ID and API key are required to enable outbound sync.")

    if not integration and has_new_creds:
        integration = IntegrationManager.customerio_track.token.create(
            team_id,
            external_id=None,
            config={"region": region},
            sensitive_config={"site_id": site_id, "api_key": api_key},
            created_by_id=created_by_id,
        )

    config, _ = OptOutSyncConfig.objects.get_or_create(team_id=team_id)
    config.track_integration_id = integration.id if integration else None
    config.track_enabled = enabled
    config.save(update_fields=["track_integration", "track_enabled"])

    return SavedConfig(
        enabled=enabled,
        has_credentials=bool(
            integration and integration.sensitive_config.get("site_id") and integration.sensitive_config.get("api_key")
        ),
    )


def remove_track_config(team_id: int) -> None:
    _delete_integrations(IntegrationManager.customerio_track.any, team_id)
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
