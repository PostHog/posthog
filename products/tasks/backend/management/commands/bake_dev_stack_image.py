from typing import Any

from django.core.management.base import BaseCommand

from products.tasks.backend.logic.services.dev_stack_image import DEV_STACK_IMAGE_NAME, bake_dev_stack_image


class Command(BaseCommand):
    help = (
        "Bake the prebaked PostHog dev-stack VM image (warm docker state + migrated databases) "
        "and publish it as a named Modal image. Dispatches the Temporal workflow by default; "
        "use --inline to run the bake in this process."
    )

    def add_arguments(self, parser: Any) -> None:
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
        if options["inline"]:
            image_id = bake_dev_stack_image(publish_name)
            self.stdout.write(self.style.SUCCESS(f"Published {publish_name} ({image_id})"))
        else:
            from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keeps the Temporal client off command discovery
                execute_bake_dev_stack_image_workflow,
            )

            execute_bake_dev_stack_image_workflow(publish_name)
            self.stdout.write(self.style.SUCCESS(f"Dispatched bake-dev-stack-image-{publish_name}"))
