from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from products.tasks.backend.logic.services.cpu_billing import CPU_BILLING_SAMPLER_PATH
from products.tasks.backend.logic.services.docker_sandbox import DockerSandbox
from products.tasks.backend.logic.services.sandbox import ExecutionResult
from products.tasks.backend.logic.services.sandbox_housekeeping import SandboxHousekeeping, parse_housekeeping_output

MEASURED_AT = datetime(2026, 10, 21, tzinfo=UTC)
MANIFEST = 'agent_manifest:{\nagent_manifest:  "name": "@posthog/agent",\nagent_manifest:  "version": "2.4.282"\nagent_manifest:}\n'
STATE = "cpu_billing_state:0 1000000 1000000000\n"
CPU_STAT = "cpu_stat:usage_usec 1500000\ncpu_stat:user_usec 1000000\n"
TIME = "time_ns:3000000000\n"


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        (MANIFEST + "sampler_exit:0\n" + STATE + CPU_STAT + TIME, ("2.4.282", True, 1_500_000, 1_000_000)),
        ("sampler_exit:1\n" + CPU_STAT + TIME, (None, False, 1_500_000, None)),
        (
            'agent_manifest:{"version": ""}\nsampler_exit:0\n'
            + STATE
            + "cpu_stat:user_usec 1000000\ncpuacct_usage:2500000000\n"
            + TIME,
            (None, True, 2_500_000, 1_500_000),
        ),
        ("agent_manifest:not json\nsampler_exit:0\n" + STATE + CPU_STAT, (None, True, 1_500_000, None)),
        ("", (None, False, None, None)),
    ],
)
def test_parse_housekeeping_output(stdout: str, expected: tuple) -> None:
    agent_version, sampler_started, cpu_usage_usec, billed_cpu_usage_usec = expected

    assert parse_housekeeping_output(stdout, 0.5, MEASURED_AT) == SandboxHousekeeping(
        agent_version=agent_version,
        cpu_billing_sampler_started=sampler_started,
        cpu_usage_usec=cpu_usage_usec,
        billed_cpu_usage_usec=billed_cpu_usage_usec,
        cpu_usage_measured_at=MEASURED_AT if cpu_usage_usec is not None else None,
    )


@pytest.mark.parametrize(
    ("execute_outcome", "expected_version"),
    [
        (ExecutionResult(stdout='agent_manifest:{"version": "1.2.3"}\n', stderr="", exit_code=0), "1.2.3"),
        (ExecutionResult(stdout="", stderr="", exit_code=0), None),
        (TimeoutError("housekeeping timed out"), None),
    ],
)
def test_docker_housekeeping_reads_only_the_agent_version(
    execute_outcome: ExecutionResult | Exception, expected_version: str | None
) -> None:
    sandbox = DockerSandbox.__new__(DockerSandbox)
    sandbox.id = "docker-sandbox"

    with patch.object(sandbox, "execute", side_effect=[execute_outcome]) as execute:
        housekeeping = sandbox.run_post_create_housekeeping()

    assert CPU_BILLING_SAMPLER_PATH not in execute.call_args.args[0]
    assert housekeeping == SandboxHousekeeping(
        agent_version=expected_version,
        cpu_billing_sampler_started=False,
        cpu_usage_usec=None,
        billed_cpu_usage_usec=None,
        cpu_usage_measured_at=None,
    )


def test_billing_housekeeping_failure_propagates_so_provisioning_retries() -> None:
    sandbox = DockerSandbox.__new__(DockerSandbox)
    sandbox.id = "billing-sandbox"

    with (
        patch.object(sandbox, "_cpu_billing_request_cores", return_value=0.5),
        patch.object(sandbox, "execute", side_effect=TimeoutError("housekeeping timed out")),
        pytest.raises(TimeoutError),
    ):
        sandbox.run_post_create_housekeeping()
