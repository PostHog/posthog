"""Background imports of opt-outs, suppressions, categories and templates from other messaging tools.

Each run executes in Temporal, so a long provider list does not hit the request timeout. The synchronous
Customer.io import in `customerio.py` stays available next to it.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.ph_client import feature_enabled_or_false

from products.messaging.backend.models.provider_import_run import (
    ImportProviderKey,
    ImportStepStatus,
    ProviderImportRun,
    ProviderImportStatus,
)
from products.messaging.backend.provider_imports import runs
from products.messaging.backend.provider_imports.base import (
    ImportCredentialsConflict,
    ImportCredentialsInvalid,
    ImportCredentialsMissing,
    ImportProvider,
    ImportProviderUnavailable,
    ImportStepSpec,
)
from products.messaging.backend.provider_imports.registry import PROVIDERS, UnknownImportProvider, get_provider

IMPORT_PROVIDER_CHOICES: list[tuple[str, str]] = [(value, str(label)) for value, label in ImportProviderKey.choices]
PROVIDER_IMPORT_STATUS_CHOICES: list[tuple[str, str]] = [
    (value, str(label)) for value, label in ProviderImportStatus.choices
]
IMPORT_STEP_STATUS_CHOICES: list[tuple[str, str]] = [(value, str(label)) for value, label in ImportStepStatus.choices]


class ProviderImportRejected(Exception):
    """The request can't start an import: unknown provider or step, or missing or invalid credentials."""


class ProviderImportConflict(Exception):
    """An import is already running, or a different API key is stored."""


class ProviderImportUnavailable(Exception):
    """The provider did not respond while checking the API key. Starting again later can work."""


@frozen
class ImportStepOption:
    key: str
    label: str
    description: str


@frozen
class ImportProviderOption:
    key: str
    label: str
    steps: tuple[ImportStepOption, ...]
    retains_credentials: bool
    api_key_label: str
    api_key_help: str
    api_key_url: str | None
    not_imported: str
    next_steps: tuple[str, ...]


@frozen
class ImportStepCount:
    key: str
    label: str
    value: int


@frozen
class ImportStepItem:
    label: str
    status: str
    url: str | None
    notes: tuple[str, ...]


@frozen
class ImportStepProgress:
    key: str
    label: str
    status: str
    processed: int
    imported: int
    warnings: tuple[str, ...]
    last_error: str | None
    counts: tuple[ImportStepCount, ...] = ()
    items: tuple[ImportStepItem, ...] = ()
    # How many warnings and items didn't fit in the run's stored progress.
    warnings_omitted: int = 0
    items_omitted: int = 0


@frozen
class ProviderImportRunState:
    id: UUID
    provider: str
    status: str
    steps: tuple[ImportStepProgress, ...]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def list_import_providers(team_uuid: str, organization_id: str) -> list[ImportProviderOption]:
    """The providers this team can import from."""
    return [
        ImportProviderOption(
            key=provider.key,
            label=provider.label,
            steps=tuple(
                ImportStepOption(key=spec.key, label=spec.label, description=spec.description)
                for spec in provider.steps
            ),
            retains_credentials=provider.retains_credentials,
            api_key_label=provider.api_key_label,
            api_key_help=provider.api_key_help,
            api_key_url=provider.api_key_url,
            not_imported=provider.not_imported,
            next_steps=provider.next_steps,
        )
        for provider in PROVIDERS.values()
        if _provider_enabled(provider, team_uuid, organization_id)
    ]


def _provider_enabled(provider: ImportProvider, team_uuid: str, organization_id: str) -> bool:
    if provider.feature_flag is None:
        return True
    return feature_enabled_or_false(
        provider.feature_flag,
        team_uuid,
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
        send_feature_flag_events=False,
    )


def start_provider_import(
    team_id: int, provider: str, steps: list[str], api_key: str | None, created_by_id: int | None
) -> ProviderImportRunState:
    """Check the credentials and start a background import of the selected steps.

    Raises ProviderImportRejected for a request that can't work as sent, ProviderImportConflict when an import is
    already running or a different key is stored, and ProviderImportUnavailable when the provider can't check the
    key.
    """
    try:
        run = runs.start_run(team_id, provider, steps, api_key, created_by_id)
    except (UnknownImportProvider, runs.InvalidImportSteps, ImportCredentialsMissing, ImportCredentialsInvalid) as e:
        raise ProviderImportRejected(_rejection_message(e)) from e
    except (runs.ProviderImportAlreadyRunning, ImportCredentialsConflict) as e:
        raise ProviderImportConflict(str(e)) from e
    except ImportProviderUnavailable as e:
        raise ProviderImportUnavailable(f"{e} Try again in a few minutes.") from e
    return _to_state(run)


def list_provider_import_runs(team_id: int, limit: int = 20) -> list[ProviderImportRunState]:
    """The team's most recent imports, newest first."""
    return [_to_state(run) for run in runs.list_runs(team_id, limit)]


def get_provider_import_run(team_id: int, run_id: UUID) -> ProviderImportRunState | None:
    run = runs.get_run(team_id, run_id)
    return _to_state(run) if run else None


def _rejection_message(error: Exception) -> str:
    if isinstance(error, UnknownImportProvider):
        return f"Unknown import provider: {error}."
    return str(error)


def _to_state(run: ProviderImportRun) -> ProviderImportRunState:
    specs = {spec.key: spec for spec in get_provider(run.provider).steps}
    return ProviderImportRunState(
        id=run.id,
        provider=run.provider,
        status=run.status,
        steps=tuple(_step_progress(step, specs.get(step), run.progress.get(step, {})) for step in run.steps),
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _step_progress(key: str, spec: ImportStepSpec | None, progress: dict[str, Any]) -> ImportStepProgress:
    counts = progress.get("counts", {})
    return ImportStepProgress(
        key=key,
        label=spec.label if spec else key,
        status=progress.get("status", ImportStepStatus.PENDING.value),
        processed=progress.get("processed", 0),
        imported=progress.get("imported", 0),
        warnings=tuple(progress.get("warnings", [])),
        last_error=progress.get("last_error"),
        counts=tuple(
            ImportStepCount(key=count_key, label=label, value=counts[count_key])
            for count_key, label in (spec.count_labels if spec else ())
            if counts.get(count_key)
        ),
        items=tuple(
            ImportStepItem(
                label=item["label"], status=item["status"], url=item.get("url"), notes=tuple(item.get("notes", []))
            )
            for item in progress.get("items", [])
        ),
        warnings_omitted=progress.get("warnings_omitted", 0),
        items_omitted=progress.get("items_omitted", 0),
    )
