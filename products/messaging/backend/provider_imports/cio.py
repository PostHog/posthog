from collections.abc import Iterator

from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID
from products.messaging.backend.models.provider_import_run import ImportProviderKey
from products.messaging.backend.provider_imports.base import (
    ImportContext,
    ImportCredentialsConflict,
    ImportCredentialsInvalid,
    ImportCredentialsMissing,
    ImportPage,
    ImportProvider,
    ImportStepSpec,
    StepCheckpoint,
    UnknownImportStep,
)
from products.messaging.backend.services import customerio_config
from products.messaging.backend.services.customerio_import_service import (
    CUSTOMERIO_SUPPRESSION_TYPES,
    CustomerIOImportService,
)

SUPPRESSION_TYPE_ORDER = tuple(CUSTOMERIO_SUPPRESSION_TYPES)


INVALID_CREDENTIALS_MESSAGE = "c.io rejected the App API key. Check that it is an App API key, that it has not expired, and that you copied all of it."


class CIOUnreachable(Exception):
    """The App API refused the stored key or did not answer. Retryable, because the API can be down for a while."""


class CIOImportProvider(ImportProvider):
    key = ImportProviderKey.CIO.value
    label = ImportProviderKey.CIO.label
    steps = (
        ImportStepSpec(
            key="categories",
            label="Subscription topics",
            description="Creates a message category for each c.io subscription topic.",
        ),
        ImportStepSpec(
            key="suppressions",
            label="Suppressed addresses",
            description=(
                "Adds the addresses that c.io's email provider bounced, marked as invalid, "
                "or got a spam report for to the suppression list."
            ),
        ),
        ImportStepSpec(
            key="opt_outs",
            label="Global unsubscribes",
            description="Opts people who unsubscribed from all c.io messages out of all marketing messages.",
        ),
    )

    def save_credentials(self, team_id: int, api_key: str | None, created_by_id: int | None) -> int:
        try:
            resolved_key = customerio_config.resolve_app_api_key(team_id, api_key)
        except customerio_config.ConfigIncomplete as e:
            raise ImportCredentialsMissing(str(e)) from e
        except customerio_config.ConfigConflict as e:
            raise ImportCredentialsConflict(str(e)) from e
        if not CustomerIOImportService(team_id, resolved_key, created_by_id).connect():
            raise ImportCredentialsInvalid(INVALID_CREDENTIALS_MESSAGE)
        return customerio_config.save_app_integration(team_id, resolved_key, created_by_id).id

    def run_step(self, step: str, context: ImportContext, checkpoint: StepCheckpoint | None) -> Iterator[ImportPage]:
        match step:
            case "categories":
                yield from self._import_categories(self._connect(context))
            case "suppressions":
                yield from self._import_suppressions(self._connect(context), checkpoint)
            case "opt_outs":
                yield from self._import_opt_outs(self._connect(context), checkpoint)
            case _:
                raise UnknownImportStep(step)

    def _connect(self, context: ImportContext) -> CustomerIOImportService:
        api_key = (
            customerio_config.stored_app_api_key(context.team_id, context.integration_id)
            if context.integration_id is not None
            else None
        )
        if not api_key:
            raise ImportCredentialsMissing("The c.io App API key was deleted. Add it again and start a new import.")
        service = CustomerIOImportService(context.team_id, api_key, context.created_by_id)
        if not service.connect():
            raise CIOUnreachable("c.io rejected the App API key or did not respond.")
        return service

    def _import_categories(self, service: CustomerIOImportService) -> Iterator[ImportPage]:
        assert service.client is not None
        topics = service.client.get_subscription_topics()
        service.import_categories(topics)
        yield ImportPage(
            processed=len(topics),
            imported=service.progress["categories_created"],
            warnings=tuple(service.progress["errors"]),
        )

    def _import_suppressions(
        self, service: CustomerIOImportService, checkpoint: StepCheckpoint | None
    ) -> Iterator[ImportPage]:
        resume_type = checkpoint.get("suppression_type") if checkpoint else None
        start_index = SUPPRESSION_TYPE_ORDER.index(resume_type) if resume_type in SUPPRESSION_TYPE_ORDER else 0
        for index in range(start_index, len(SUPPRESSION_TYPE_ORDER)):
            suppression_type = SUPPRESSION_TYPE_ORDER[index]
            offset = int(checkpoint.get("offset", 0)) if checkpoint and suppression_type == resume_type else 0
            for page in service.fetch_suppression_pages(suppression_type, offset):
                imported = service.save_suppression_page(page)
                next_checkpoint: StepCheckpoint | None
                if not page.is_last:
                    next_checkpoint = {"suppression_type": suppression_type, "offset": page.next_offset}
                elif index + 1 < len(SUPPRESSION_TYPE_ORDER):
                    next_checkpoint = {"suppression_type": SUPPRESSION_TYPE_ORDER[index + 1], "offset": 0}
                else:
                    next_checkpoint = None
                yield ImportPage(processed=page.entries, imported=imported, checkpoint=next_checkpoint)

    def _import_opt_outs(
        self, service: CustomerIOImportService, checkpoint: StepCheckpoint | None
    ) -> Iterator[ImportPage]:
        start = checkpoint.get("start") if checkpoint else None
        for page in service.fetch_global_unsubscribe_pages(start=str(start) if start else None):
            if page.emails:
                service.save_opt_outs(list(page.emails), [ALL_MESSAGE_PREFERENCE_CATEGORY_ID])
            yield ImportPage(
                processed=page.customers,
                imported=len(page.emails),
                checkpoint={"start": page.next_start} if page.next_start else None,
            )
