import base64
import secrets
from uuid import UUID

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from posthog.models.user import User

from products.growth.backend.models import AccountAuditCredential

SOURCE_TEAM_ID = 2


class Command(BaseCommand):
    def add_arguments(self, parser) -> None:
        parser.add_argument("--owner-id", required=True, type=int)
        parser.add_argument("--workflow-id", required=True)
        parser.add_argument("--rotate-key-id")

    def handle(self, *args, **options) -> None:
        owner = User.objects.filter(id=options["owner_id"], is_active=True, is_staff=True).first()
        if owner is None:
            raise CommandError("The owner must be an active staff user.")
        try:
            workflow_id = UUID(options["workflow_id"])
        except ValueError as error:
            raise CommandError("workflow-id must be a UUID.") from error
        if (
            not apps.get_model("workflows", "HogFlow")
            .objects.filter(
                id=workflow_id,
                team_id=SOURCE_TEAM_ID,
                status="active",
                created_by_id=owner.id,
            )
            .exists()
        ):
            raise CommandError("The workflow must be active in team 2 and owned by the staff user.")

        rotated_credential = None
        if options["rotate_key_id"]:
            try:
                rotated_key_id = UUID(options["rotate_key_id"])
            except ValueError as error:
                raise CommandError("rotate-key-id must be a UUID.") from error
            rotated_credential = (
                AccountAuditCredential.objects.only("id", "is_active")
                .filter(public_key_id=rotated_key_id, owner_id=owner.id, workflow_id=workflow_id)
                .first()
            )
            if rotated_credential is None:
                raise CommandError("The credential to rotate was not found.")

        signing_secret = f"whsec_{base64.b64encode(secrets.token_bytes(32)).decode()}"
        with transaction.atomic():
            credential = AccountAuditCredential.objects.create(
                owner=owner,
                workflow_id=workflow_id,
                signing_secret=signing_secret,
            )
            if rotated_credential is not None:
                rotated_credential.is_active = False
                rotated_credential.save(update_fields=["is_active"])
        self.stdout.write(f"key_id={credential.public_key_id}")
        self.stdout.write(f"signing_secret={signing_secret}")
