import re
import json
import time
import logging

from products.tasks.backend.dev_stack_image_models import DevStackImageAttempt
from products.tasks.backend.logic.services.sandbox import (
    ExecutionResult,
    SandboxConfig,
    SandboxTemplate,
    get_sandbox_class,
)

logger = logging.getLogger(__name__)


def _log_command_failure(
    result: ExecutionResult, stage: str, attempt: DevStackImageAttempt | None, image_id: str, sandbox_id: str
) -> None:
    logger.error(
        "dev_stack_image_verification_command_failed",
        extra={
            "stage": stage,
            "exit_code": result.exit_code,
            "attempt_id": str(attempt.id) if attempt else None,
            "image_id": image_id,
            "sandbox_id": sandbox_id,
            "stdout_tail": result.stdout.encode()[-4_000:].decode(errors="ignore"),
            "stderr_tail": result.stderr.encode()[-4_000:].decode(errors="ignore"),
        },
    )


class DevStackImageVerificationError(Exception):
    pass


def verify_dev_stack_image(attempt: DevStackImageAttempt | None, image_id: str) -> str:
    config = SandboxConfig(
        name="dev-stack-image-verification",
        template=SandboxTemplate.VM_BASE,
        base_image_reference=(attempt.base_reference or None) if attempt else None,
        snapshot_external_id=image_id,
        require_snapshot=True,
        vm_runtime=True,
        ttl_seconds=15 * 60,
        default_execution_timeout_seconds=5 * 60,
        memory_gb=32,
        cpu_cores=8,
    )
    sandbox = get_sandbox_class().create(config)
    try:
        if not config.snapshot_restored:
            raise RuntimeError("Candidate snapshot could not be restored")
        manifest = sandbox.execute("cat /opt/posthog/dev-stack-bake.json")
        if manifest.exit_code != 0:
            _log_command_failure(manifest, "manifest", attempt, image_id, sandbox.id)
            raise DevStackImageVerificationError("Bake manifest is missing")
        try:
            observed = json.loads(manifest.stdout)
        except ValueError as error:
            raise DevStackImageVerificationError("Invalid bake manifest") from error
        if not isinstance(observed, dict):
            raise DevStackImageVerificationError("Invalid bake manifest")
        if attempt and any(
            expected and observed.get(key) != expected
            for key, expected in (
                ("base_reference", attempt.base_reference),
                ("posthog_sha", attempt.repository_sha),
                ("recipe_sha", attempt.recipe_sha),
            )
        ):
            raise DevStackImageVerificationError("Candidate inputs do not match the requested generation")
        agent = sandbox.execute("node -p \"require('/scripts/node_modules/@posthog/agent/package.json').version\"")
        version = agent.stdout.strip()
        if (
            agent.exit_code != 0
            or not version
            or (attempt and attempt.recipe_sha and observed.get("agent_version") != version)
        ):
            _log_command_failure(agent, "agent", attempt, image_id, sandbox.id)
            raise DevStackImageVerificationError("Candidate agent version does not match its manifest")
        repository_sha = observed.get("posthog_sha")
        if not isinstance(repository_sha, str) or re.fullmatch(r"[0-9a-f]{40}", repository_sha) is None:
            raise DevStackImageVerificationError("Invalid bake repository revision")
        restored = sandbox.execute(
            "set -e; repo=/tmp/workspace/repos/posthog/posthog; "
            'git init "$repo"; '
            f'git -C "$repo" fetch --depth 1 https://github.com/PostHog/posthog.git {repository_sha}; '
            'git -C "$repo" checkout --force --detach FETCH_HEAD; '
            f'test "$(git -C "$repo" rev-parse HEAD)" = {repository_sha}',
            timeout_seconds=5 * 60,
        )
        if restored.exit_code != 0:
            _log_command_failure(restored, "checkout", attempt, image_id, sandbox.id)
            raise RuntimeError("Verification checkout could not be restored")
        result = sandbox.execute(
            "set -e; /usr/local/bin/bootstrap-dev-stack; "
            "docker start posthog-db-1 posthog-redis7-1 posthog-clickhouse-1; "
            "for attempt in $(seq 1 60); do "
            "if docker exec posthog-db-1 pg_isready -U posthog && "
            "docker exec posthog-redis7-1 redis-cli ping | grep -qx PONG && "
            "docker exec posthog-clickhouse-1 clickhouse-client --query 'SELECT 1'; "
            "then exit 0; fi; sleep 3; done; exit 1",
            timeout_seconds=5 * 60,
        )
        if result.exit_code != 0:
            _log_command_failure(result, "datastores", attempt, image_id, sandbox.id)
            raise DevStackImageVerificationError("Candidate datastores did not become ready")
        return version
    finally:
        for cleanup_attempt in range(3):
            try:
                sandbox.destroy()
                break
            except Exception:
                if cleanup_attempt < 2:
                    time.sleep(2**cleanup_attempt)
                else:
                    logger.exception(
                        "dev_stack_image_verification_cleanup_failed",
                        extra={
                            "attempt_id": str(attempt.id) if attempt else None,
                            "image_id": image_id,
                            "sandbox_id": sandbox.id,
                        },
                    )
