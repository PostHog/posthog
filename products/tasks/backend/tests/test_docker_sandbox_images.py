import hashlib
import subprocess
from pathlib import Path

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.logic.services.docker_sandbox import NOTEBOOK_IMAGE_NAME, DockerSandbox, SandboxTemplate

NOTEBOOK_DOCKERFILE = Path(__file__).parents[1] / "sandbox" / "images" / "Dockerfile.sandbox-notebook"


def _inspect_result(returncode: int, label: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=label, stderr="")


class TestNotebookImageFreshness(SimpleTestCase):
    @parameterized.expand(
        [
            ("built_from_current_dockerfile", 0, "current", False),
            ("built_from_older_dockerfile", 0, "0" * 64, True),
            ("built_before_the_stamp_existed", 0, "<no value>", True),
            ("missing", 1, "", False),
        ]
    )
    def test_rebuilds_only_when_the_dockerfile_changed(
        self, _name: str, returncode: int, label: str, expect_force: bool
    ) -> None:
        current_sha = hashlib.sha256(NOTEBOOK_DOCKERFILE.read_bytes()).hexdigest()
        stamp = current_sha if label == "current" else label
        with (
            patch.object(DockerSandbox, "_run", return_value=_inspect_result(returncode, stamp)),
            patch.object(DockerSandbox, "_build_image_if_needed") as build,
        ):
            DockerSandbox._ensure_image_exists(SandboxTemplate.NOTEBOOK_BASE)

        build.assert_called_once()
        self.assertEqual(build.call_args.args[0], NOTEBOOK_IMAGE_NAME)
        self.assertEqual(build.call_args.kwargs["force"], expect_force)
