import shlex

import pytest
from unittest.mock import patch

from django.test import override_settings

from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode

from products.wizard.backend.logic.workers.commands import build_wizard_command


class CommandSnapshotExtension(SingleFileSnapshotExtension):
    file_extension = "txt"
    _write_mode = WriteMode.TEXT


@pytest.mark.parametrize(
    "region,debug,use_local_wizard_source,program_command,gateway_token_file",
    [
        pytest.param("US", False, False, (), None, id="default-us"),
        pytest.param("EU", False, False, ("audit", "web-analytics"), None, id="audit-eu"),
        pytest.param("US", True, False, (), "/tmp/gateway-token", id="debug-package"),
        pytest.param("EU", True, True, ("audit", "web-analytics"), None, id="debug-local"),
        pytest.param("US", True, True, ("audit", "spend"), "/tmp/gateway-token", id="debug-local-gateway-token"),
    ],
)
def test_wizard_command(
    snapshot: SnapshotAssertion,
    region: str,
    debug: bool,
    use_local_wizard_source: bool,
    program_command: tuple[str, ...],
    gateway_token_file: str | None,
) -> None:
    with (
        override_settings(DEBUG=debug, LOCAL_WIZARD_GATEWAY_TOKEN_FILE=gateway_token_file),
        patch("products.wizard.backend.logic.workers.commands.get_instance_region", return_value=region),
    ):
        command = build_wizard_command(
            "/workspace/example user's project",
            7,
            "2.67.0",
            program_command,
            use_local_wizard_source=use_local_wizard_source,
        )

    script = shlex.split(command)[-1]
    readable_script = script.replace(" && ", "\n")
    assert f"{command}\n\nShell script:\n{readable_script}\n" == snapshot(extension_class=CommandSnapshotExtension)
