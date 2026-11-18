from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.warehouse_sources.backend.temporal.data_imports.sources.common.credential_auth_type import (
    CREDENTIAL_AUTH_TYPES_PATH,
    render_credential_auth_types,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.credential_kind import (
    CREDENTIAL_KINDS_PATH,
    ChangedFrozenValueError,
    render_credential_kinds,
)


class Command(BaseCommand):
    help = (
        "Write the frozen credential kind of each source and the default auth type of each kind. "
        "`hogli build:projections` writes these and the field classification audit. Use this command only with "
        "--allow-changed-defaults, to accept a changed value of an existing entry."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--allow-changed-defaults",
            action="store_true",
            help=(
                "Write a changed credential kind or default auth type for an existing entry. Integration rows "
                "store these values, so the change needs a data migration."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        allow_changed = options["allow_changed_defaults"]
        try:
            # Render both before writing either, so a refused change writes nothing.
            kinds = render_credential_kinds(allow_changed=allow_changed)
            auth_types = render_credential_auth_types(allow_changed=allow_changed)
        except ChangedFrozenValueError as error:
            raise CommandError(str(error)) from error
        CREDENTIAL_KINDS_PATH.write_text(kinds)
        self.stdout.write(self.style.SUCCESS(f"Wrote {CREDENTIAL_KINDS_PATH}"))
        CREDENTIAL_AUTH_TYPES_PATH.write_text(auth_types)
        self.stdout.write(self.style.SUCCESS(f"Wrote {CREDENTIAL_AUTH_TYPES_PATH}"))
