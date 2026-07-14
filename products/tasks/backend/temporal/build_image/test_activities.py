import random

import pytest
from unittest.mock import MagicMock, patch

from modal.exception import RemoteError

from posthog.models import Organization, Team

from products.tasks.backend.models import SandboxCustomImage
from products.tasks.backend.temporal.build_image.activities import (
    BuildAndPublishOutput,
    ImageBuildActivityInput,
    build_and_publish_image,
)

COMPOSE_PATH = "products.tasks.backend.temporal.build_image.activities._compose_modal_image"


def _building_image() -> SandboxCustomImage:
    org = Organization.objects.create(name=f"ImgOrg-{random.randint(1, 99999)}")
    team = Team.objects.create(organization=org, name=f"ImgTeam-{random.randint(1, 99999)}")
    return SandboxCustomImage.objects.create(
        team=team,
        name="custom",
        spec={"apt_packages": ["some-package"]},
        status=SandboxCustomImage.Status.BUILDING,
    )


@pytest.mark.django_db(transaction=True)
def test_modal_build_failure_is_returned_not_raised(activity_environment):
    # A user's bad spec makes Modal raise RemoteError. That's an expected build failure, so the
    # activity must hand it back as a result (keeping it out of error tracking and off the retry
    # budget), not let it propagate. If someone re-introduces the raise, this fails.
    image = _building_image()
    modal_image = MagicMock()
    modal_image.build.side_effect = RemoteError("Image build for im-123 failed. See build logs for more details.")

    with patch(COMPOSE_PATH, return_value=(modal_image, MagicMock())), patch("modal.enable_output"):
        result = activity_environment.run(
            build_and_publish_image,
            ImageBuildActivityInput(image_id=str(image.id), team_id=image.team_id),
        )

    assert isinstance(result, BuildAndPublishOutput)
    assert result.modal_image_name is None
    assert "failed" in (result.build_failed_error or "")

    # Left BUILDING for the workflow's mark_image_build_failed step; nothing published.
    image.refresh_from_db()
    assert image.status == SandboxCustomImage.Status.BUILDING
    assert image.version == 0
    assert image.modal_image_name == ""


@pytest.mark.django_db(transaction=True)
def test_unexpected_build_error_still_propagates(activity_environment):
    # Only a Modal RemoteError is a domain outcome — a genuine defect (here an OOM) must still reach
    # error tracking, so it has to propagate. Guards against widening the catch to bare Exception.
    image = _building_image()
    modal_image = MagicMock()
    modal_image.build.side_effect = RuntimeError("worker ran out of memory")

    with patch(COMPOSE_PATH, return_value=(modal_image, MagicMock())), patch("modal.enable_output"):
        with pytest.raises(RuntimeError, match="worker ran out of memory"):
            activity_environment.run(
                build_and_publish_image,
                ImageBuildActivityInput(image_id=str(image.id), team_id=image.team_id),
            )
