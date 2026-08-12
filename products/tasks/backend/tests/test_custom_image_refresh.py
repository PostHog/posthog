from collections.abc import Callable
from datetime import timedelta
from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from products.tasks.backend.logic.services.custom_image_refresh import refresh_stale_sandbox_custom_images
from products.tasks.backend.models import SandboxCustomImage
from products.tasks.backend.temporal.build_image.activities import MarkImageBuildFailedInput, mark_image_build_failed


class TestCustomImageRefresh(APIBaseTest):
    def _create_image(self, *, base_image_reference: str | None) -> SandboxCustomImage:
        image_count = SandboxCustomImage.objects.for_team(self.team.id).count()
        return SandboxCustomImage.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            created_by=self.user,
            name=f"image-{image_count}",
            spec={"apt_packages": ["git"]},
            status=SandboxCustomImage.Status.READY,
            modal_image_name=f"posthog-sandbox-custom-{image_count}:latest",
            base_image_reference=base_image_reference,
        )

    @patch("products.tasks.backend.logic.services.custom_image_refresh.execute_build_sandbox_image_workflow")
    @patch(
        "products.tasks.backend.logic.services.custom_image_refresh.resolve_template_base_image_reference",
        return_value="ghcr.io/posthog/posthog-sandbox-vm@sha256:current",
    )
    def test_refresh_dispatches_oldest_stale_image_with_batch_limit(self, _mock_reference, mock_execute) -> None:
        oldest_stale = self._create_image(base_image_reference=None)
        newer_stale = self._create_image(base_image_reference="ghcr.io/posthog/posthog-sandbox-vm@sha256:old")
        current = self._create_image(base_image_reference="ghcr.io/posthog/posthog-sandbox-vm@sha256:current")
        SandboxCustomImage.objects.for_team(self.team.id).filter(id=oldest_stale.id).update(
            updated_at=timezone.now() - timedelta(days=1)
        )

        dispatched = refresh_stale_sandbox_custom_images(batch_size=1)

        assert dispatched == 1
        mock_execute.assert_called_once_with(str(oldest_stale.id), self.team.id, refresh=True)
        oldest_stale.refresh_from_db()
        newer_stale.refresh_from_db()
        current.refresh_from_db()
        assert oldest_stale.status == SandboxCustomImage.Status.BUILDING
        assert newer_stale.status == SandboxCustomImage.Status.READY
        assert current.status == SandboxCustomImage.Status.READY

        already_attempted = self._create_image(base_image_reference="ghcr.io/posthog/posthog-sandbox-vm@sha256:old")
        already_attempted.base_image_refresh_reference = "ghcr.io/posthog/posthog-sandbox-vm@sha256:current"
        already_attempted.save(update_fields=["base_image_refresh_reference"])

        assert refresh_stale_sandbox_custom_images() == 1
        already_attempted.refresh_from_db()
        assert already_attempted.status == SandboxCustomImage.Status.READY

    @patch(
        "products.tasks.backend.logic.services.custom_image_refresh.execute_build_sandbox_image_workflow",
        side_effect=RuntimeError("temporal unavailable"),
    )
    @patch(
        "products.tasks.backend.logic.services.custom_image_refresh.resolve_template_base_image_reference",
        return_value="ghcr.io/posthog/posthog-sandbox-vm@sha256:current",
    )
    def test_refresh_restores_ready_status_when_dispatch_fails(self, _mock_reference, _mock_execute) -> None:
        stale = self._create_image(base_image_reference="ghcr.io/posthog/posthog-sandbox-vm@sha256:old")

        dispatched = refresh_stale_sandbox_custom_images()

        assert dispatched == 0
        stale.refresh_from_db()
        assert stale.status == SandboxCustomImage.Status.READY
        assert stale.base_image_refresh_reference is None

    def test_refresh_build_failure_remains_ready_and_can_retry(self) -> None:
        stale = self._create_image(base_image_reference="ghcr.io/posthog/posthog-sandbox-vm@sha256:old")
        stale.status = SandboxCustomImage.Status.BUILDING
        stale.base_image_refresh_reference = "ghcr.io/posthog/posthog-sandbox-vm@sha256:current"
        stale.save(update_fields=["status", "base_image_refresh_reference"])

        activity_body = cast(Callable[[MarkImageBuildFailedInput], None], vars(mark_image_build_failed)["__wrapped__"])
        activity_body(
            MarkImageBuildFailedInput(
                image_id=str(stale.id),
                team_id=self.team.id,
                error="transient build failure",
                refresh=True,
            )
        )

        stale.refresh_from_db()
        assert stale.status == SandboxCustomImage.Status.READY
        assert stale.error == "transient build failure"
        assert stale.base_image_refresh_reference is None
