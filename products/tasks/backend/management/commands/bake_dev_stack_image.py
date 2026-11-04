from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from posthog.utils import get_instance_region

from products.tasks.backend.dev_stack_image_models import DevStackImageAttempt, DevStackImageTarget
from products.tasks.backend.logic.services.dev_stack_image import DEV_STACK_IMAGE_NAME, bake_dev_stack_image
from products.tasks.backend.logic.services.dev_stack_image_refresh import reconcile_dev_stack_image
from products.tasks.backend.logic.services.dev_stack_image_state import DevStackImageState
from products.tasks.backend.logic.services.dev_stack_image_verification import verify_dev_stack_image


class Command(BaseCommand):
    help = (
        "Bake the PostHog dev-stack image through Temporal. Initialize protected activation "
        "after deploying all readers and workers, then enable regional reconciliation. "
        "Inline bakes are available only before protected activation is initialized."
    )

    def add_arguments(self, parser: Any) -> None:
        lifecycle = parser.add_mutually_exclusive_group()
        lifecycle.add_argument("--initialize", action="store_true")
        lifecycle.add_argument("--enable", action="store_true")
        lifecycle.add_argument("--disable", action="store_true")
        lifecycle.add_argument("--rollback-attempt", type=UUID)
        parser.add_argument("--request-key", default="")
        parser.add_argument("--seed-image-id")
        parser.add_argument(
            "--publish-name",
            default=DEV_STACK_IMAGE_NAME,
            help=f"Modal image name to publish under (default: {DEV_STACK_IMAGE_NAME})",
        )
        parser.add_argument(
            "--inline",
            action="store_true",
            help="Run the bake synchronously in this process instead of dispatching the Temporal workflow",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        publish_name: str = options["publish_name"]
        if sum(bool(options[key]) for key in ("initialize", "enable", "disable", "rollback_attempt")) > 1:
            raise CommandError("Choose only one of --initialize, --enable, --disable, or --rollback-attempt")
        if options["seed_image_id"] and not options["initialize"]:
            raise CommandError("--seed-image-id requires --initialize")
        if len(options["request_key"]) > 128:
            raise CommandError("Request IDs must be at most 128 characters")
        if options["initialize"]:
            if publish_name != DEV_STACK_IMAGE_NAME:
                raise CommandError("Protected activation supports the default dev-stack image only")
            if DevStackImageState.target(publish_name) is not None:
                raise CommandError("This region already uses protected reads")
            image_id = options["seed_image_id"] or ""
            version = verify_dev_stack_image(None, image_id) if image_id else ""
            with transaction.atomic():
                initialized, created = DevStackImageTarget.objects.using("default").get_or_create(
                    region=get_instance_region() or "DEV",
                    name=publish_name,
                    defaults={
                        "active_image_id": image_id,
                        "active_agent_version": version,
                        "activated_at": timezone.now() if image_id else None,
                    },
                )
                if not created:
                    raise CommandError("This region already uses protected reads")
                if image_id:
                    seed = DevStackImageAttempt.objects.using("default").create(
                        target=initialized,
                        generation=0,
                        base_reference="",
                        repository_sha="",
                        recipe_sha="",
                        status=DevStackImageAttempt.Status.ACTIVE,
                        candidate_image_id=image_id,
                        verified_at=initialized.activated_at,
                        finished_at=initialized.activated_at,
                    )
                    self.stdout.write(f"Verified seed retained for rollback: {seed.id} (provenance unknown).")
            self.stdout.write("Protected image reads initialized. Baking remains disabled until --enable.")
            return
        target = DevStackImageState.target(publish_name)
        if options["rollback_attempt"] and target is None:
            raise CommandError("Rollback requires protected activation")
        if options["enable"] or options["disable"]:
            if target is None:
                raise CommandError("Initialize first and choose either --enable or --disable")
            target.enabled = options["enable"]
            if target.enabled:
                target.auto_refresh = True
            target.save(update_fields=["enabled", "auto_refresh"])
            self.stdout.write(
                "Bake scheduling enabled." if target.enabled else "Bake scheduling disabled. Active image retained."
            )
            return
        if target is not None:
            if options["inline"]:
                raise CommandError("Protected images require Temporal; omit --inline")
            if options["rollback_attempt"]:
                if not target.enabled:
                    raise CommandError("Enable scheduling before requesting a rollback")
                DevStackImageState(target.pk).rollback(options["rollback_attempt"])
                target.refresh_from_db(using="default")
            dispatched = reconcile_dev_stack_image(target, trigger="manual", request_key=options["request_key"])
            self.stdout.write(
                "Bake scheduled." if dispatched else "No bake dispatched. Check enablement and retry state."
            )
            return
        if options["inline"]:
            image_id = bake_dev_stack_image(publish_name)
            self.stdout.write(self.style.SUCCESS(f"Published {publish_name} ({image_id})"))
        else:
            from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keeps the Temporal client off command discovery
                execute_bake_dev_stack_image_workflow,
            )

            execute_bake_dev_stack_image_workflow(publish_name)
            self.stdout.write(self.style.SUCCESS(f"Dispatched bake-dev-stack-image-{publish_name}"))
