import logging
from collections.abc import Iterator
from functools import partial

from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID
from products.messaging.backend.models.provider_import_run import ImportProviderKey
from products.messaging.backend.provider_imports.base import (
    ImportContext,
    ImportCredentials,
    ImportCredentialsConflict,
    ImportCredentialsInvalid,
    ImportCredentialsMissing,
    ImportPage,
    ImportProvider,
    ImportProviderUnavailable,
    ImportStepSpec,
    SavedPage,
    StepCheckpoint,
    UnknownImportStep,
)
from products.messaging.backend.services import customerio_config
from products.messaging.backend.services.customerio_client import CustomerIOAPIError
from products.messaging.backend.services.customerio_import_service import (
    CUSTOMERIO_SUPPRESSION_TYPES,
    CustomerIOImportService,
    GlobalUnsubscribePage,
    SuppressionPage,
)

logger = logging.getLogger(__name__)

SUPPRESSION_TYPE_ORDER = tuple(CUSTOMERIO_SUPPRESSION_TYPES)
# The key check runs on the request path and tries both regions, so it gets a shorter timeout than the import steps.
CREDENTIAL_CHECK_TIMEOUT_SECONDS = 10
INVALID_CREDENTIALS_MESSAGE = (
    "Customer.io rejected the App API key. Check that it is an App API key, that it has not expired, "
    "and that you copied all of it."
)


class CustomerIOImportProvider(ImportProvider):
    key = ImportProviderKey.CUSTOMERIO.value
    label = ImportProviderKey.CUSTOMERIO.label
    steps = (
        ImportStepSpec(
            key="categories",
            label="Subscription topics",
            description="Creates a message category for each Customer.io subscription topic.",
        ),
        ImportStepSpec(
            key="suppressions",
            label="Suppressed addresses",
            description=(
                "Adds the addresses that Customer.io's email provider bounced, marked as invalid, "
                "or got a spam report for to the suppression list."
            ),
        ),
        ImportStepSpec(
            key="opt_outs",
            label="Global unsubscribes",
            description="Opts people who unsubscribed from all Customer.io messages out of all marketing messages.",
        ),
    )

    def check_credentials(self, team_id: int, api_key: str | None) -> ImportCredentials:
        try:
            resolved_key = customerio_config.resolve_app_api_key(team_id, api_key)
        except customerio_config.ConfigIncomplete as e:
            raise ImportCredentialsMissing(str(e)) from e
        except customerio_config.ConfigConflict as e:
            raise ImportCredentialsConflict(str(e)) from e
        try:
            connected = CustomerIOImportService(team_id, resolved_key, None).connect(
                timeout=CREDENTIAL_CHECK_TIMEOUT_SECONDS
            )
        except CustomerIOAPIError as e:
            raise ImportProviderUnavailable(_api_error_message(e)) from e
        if not connected:
            raise ImportCredentialsInvalid(INVALID_CREDENTIALS_MESSAGE)
        return ImportCredentials(api_key=resolved_key)

    def store_credentials(self, team_id: int, credentials: ImportCredentials, created_by_id: int | None) -> int:
        return customerio_config.save_app_integration(team_id, credentials.api_key, created_by_id).id

    def run_step(self, step: str, context: ImportContext, checkpoint: StepCheckpoint | None) -> Iterator[ImportPage]:
        try:
            match step:
                case "categories":
                    yield from self._fetch_categories(self._connect(context))
                case "suppressions":
                    yield from self._fetch_suppressions(self._connect(context), checkpoint)
                case "opt_outs":
                    yield from self._fetch_opt_outs(self._connect(context), checkpoint)
                case _:
                    raise UnknownImportStep(f"Customer.io has no import step named {step}.")
        except CustomerIOAPIError as e:
            raise ImportProviderUnavailable(_api_error_message(e)) from e

    def _connect(self, context: ImportContext) -> CustomerIOImportService:
        api_key = (
            customerio_config.stored_app_api_key(context.team_id, context.integration_id)
            if context.integration_id is not None
            else None
        )
        if not api_key:
            raise ImportCredentialsMissing(
                "The Customer.io App API key was deleted. Add it again and start a new import."
            )
        service = CustomerIOImportService(context.team_id, api_key, context.created_by_id)
        if not service.connect():
            raise ImportCredentialsInvalid(INVALID_CREDENTIALS_MESSAGE)
        return service

    def _fetch_categories(self, service: CustomerIOImportService) -> Iterator[ImportPage]:
        assert service.client is not None
        topics = service.client.get_subscription_topics()
        yield ImportPage(processed=len(topics), save=partial(_save_categories, service, topics))

    def _fetch_suppressions(
        self, service: CustomerIOImportService, checkpoint: StepCheckpoint | None
    ) -> Iterator[ImportPage]:
        resume_type = checkpoint.get("suppression_type") if checkpoint else None
        start_index = SUPPRESSION_TYPE_ORDER.index(resume_type) if resume_type in SUPPRESSION_TYPE_ORDER else 0
        for index in range(start_index, len(SUPPRESSION_TYPE_ORDER)):
            suppression_type = SUPPRESSION_TYPE_ORDER[index]
            offset = int(checkpoint.get("offset", 0)) if checkpoint and suppression_type == resume_type else 0
            for page in service.fetch_suppression_pages(suppression_type, offset):
                next_checkpoint: StepCheckpoint | None
                if not page.is_last:
                    next_checkpoint = {"suppression_type": suppression_type, "offset": page.next_offset}
                elif index + 1 < len(SUPPRESSION_TYPE_ORDER):
                    next_checkpoint = {"suppression_type": SUPPRESSION_TYPE_ORDER[index + 1], "offset": 0}
                else:
                    next_checkpoint = None
                yield ImportPage(
                    processed=page.entries, save=partial(_save_suppressions, service, page), checkpoint=next_checkpoint
                )

    def _fetch_opt_outs(
        self, service: CustomerIOImportService, checkpoint: StepCheckpoint | None
    ) -> Iterator[ImportPage]:
        start = checkpoint.get("start") if checkpoint else None
        for page in service.fetch_global_unsubscribe_pages(start=str(start) if start else None):
            yield ImportPage(
                processed=page.customers,
                save=partial(_save_opt_outs, service, page),
                checkpoint={"start": page.next_start} if page.next_start else None,
            )


def _save_categories(service: CustomerIOImportService, topics: list[dict]) -> SavedPage:
    service.import_categories(topics)
    errors = service.progress["errors"]
    if not errors:
        return SavedPage(imported=service.progress["categories_created"])
    # The service's errors hold raw exception text, which stays in the server log.
    logger.warning("Customer.io topics failed to import", extra={"team_id": service.team_id, "errors": errors})
    return SavedPage(
        imported=service.progress["categories_created"],
        warnings=(f"{len(errors)} subscription topics couldn't be imported. Run the import again to retry them.",),
    )


def _save_suppressions(service: CustomerIOImportService, page: SuppressionPage) -> SavedPage:
    return SavedPage(imported=service.save_suppression_page(page))


def _save_opt_outs(service: CustomerIOImportService, page: GlobalUnsubscribePage) -> SavedPage:
    if not page.emails:
        return SavedPage(imported=0)
    return SavedPage(imported=service.save_opt_outs(list(page.emails), [ALL_MESSAGE_PREFERENCE_CATEGORY_ID]))


def _api_error_message(error: CustomerIOAPIError) -> str:
    if error.status_code is None:
        return "Customer.io did not respond."
    return f"Customer.io returned HTTP {error.status_code}."
