from __future__ import annotations

import io
import time
import shlex
import base64
import hashlib
import logging
from collections.abc import Buffer
from typing import TYPE_CHECKING
from uuid import uuid4

from django.conf import settings

from posthog.storage import object_storage

from products.tasks.backend.logic.services.sandbox import redact_sandbox_command
from products.tasks.backend.models import TaskRun

if TYPE_CHECKING:
    from products.tasks.backend.logic.services.sandbox import ExecutionStream, SandboxBase


logger = logging.getLogger(__name__)


def remaining_seconds(deadline: float | None, maximum: int) -> int:
    remaining = maximum if deadline is None else min(maximum, int(deadline - time.time()))
    if remaining <= 0:
        raise RuntimeError("Workspace recovery deadline expired")
    return remaining


class SandboxArchiveReader(io.RawIOBase):
    def __init__(self, execution: ExecutionStream, deadline: float) -> None:
        super().__init__()
        self.execution = execution
        self.output = iter(execution.iter_stdout())
        self.deadline = deadline
        self.encoded = ""
        self.decoded = b""
        self.size = 0
        self.partial = False
        self.finished = False
        self.read_error: Exception | None = None

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Buffer) -> int:
        view = memoryview(buffer).cast("B")
        if not view:
            return 0
        try:
            while not self.decoded and not self.finished:
                remaining_seconds(self.deadline, 240)
                chunk = next(self.output, None)
                if chunk is None:
                    result = self.execution.wait()
                    if result.exit_code not in {0, 1} or self.encoded:
                        stderr = redact_sandbox_command(result.stderr)[-4096:]
                        raise RuntimeError(
                            f"Unable to archive the retained workspace (exit {result.exit_code}): {stderr}"
                        )
                    self.partial = result.exit_code == 1
                    self.finished = True
                    break
                self.encoded += "".join(chunk.split())
                length = len(self.encoded) // 4 * 4
                self.decoded = base64.b64decode(self.encoded[:length], validate=True)
                self.encoded = self.encoded[length:]
        except Exception as error:
            self.read_error = error
            raise
        length = min(len(view), len(self.decoded))
        view[:length] = self.decoded[:length]
        self.decoded = self.decoded[length:]
        self.size += length
        return length


class SandboxRecoveryArchive:
    @staticmethod
    def storage_path(run: TaskRun, sandbox_id: str) -> str:
        generation = hashlib.sha256(sandbox_id.encode()).hexdigest()
        return f"{settings.OBJECT_STORAGE_TASKS_FOLDER}/recovery/team_{run.team_id}/task_{run.task_id}/run_{run.id}/{generation}/workspace.tar.gz"

    @classmethod
    def is_verified(cls, run: TaskRun, sandbox_id: str) -> bool:
        return (run.state or {}).get(
            "sandbox_recovery_archive_sandbox_id"
        ) == sandbox_id and object_storage.head_object(cls.storage_path(run, sandbox_id)) is not None

    @classmethod
    def create(cls, run: TaskRun, sandbox: SandboxBase, *, deadline: float | None = None) -> None:
        if (run.state or {}).get("sandbox_recovery_archive_sandbox_id") == sandbox.id:
            return
        storage_path = cls.storage_path(run, sandbox.id)
        timeout = remaining_seconds(deadline, 240)
        command = "set -o pipefail; /usr/bin/tar --exclude='*/.git/config' --exclude='*/.git/config.worktree' --exclude='*/.git/worktrees/*/config.worktree' -czf - -C /tmp/workspace . | /usr/bin/base64 -w 65536"
        pid_path = f"/tmp/posthog-recovery-{uuid4().hex}.pid"
        launcher = (
            f"echo $$ > {pid_path}; exec /usr/bin/timeout --kill-after=5 {timeout} /bin/bash -c {shlex.quote(command)}"
        )
        execution = sandbox.execute_stream(
            f"/usr/bin/setsid --wait /bin/bash -c {shlex.quote(launcher)}",
            timeout_seconds=timeout,
            isolated=True,
            buffer_stdout=False,
        )
        reader: SandboxArchiveReader | None = None
        try:
            transfer_deadline = time.time() + timeout
            reader = SandboxArchiveReader(
                execution, min(deadline, transfer_deadline) if deadline else transfer_deadline
            )
            with io.BufferedReader(reader) as stream:
                try:
                    object_storage.write_stream(
                        storage_path, stream, extras={"Tagging": f"ttl_days=30&team_id={run.team_id}"}
                    )
                except Exception:
                    if reader.read_error is not None:
                        raise reader.read_error from None
                    raise
        finally:
            stop_command = f"/bin/rm -f {pid_path}"
            if reader is None or not reader.finished:
                stop_command = (
                    f"recovery_pid=$(/bin/cat {pid_path} 2>/dev/null) || exit 0; "
                    'case "$recovery_pid" in ""|*[!0-9]*) exit 1;; esac; '
                    '[ "$recovery_pid" -gt 1 ] || exit 1; '
                    '/bin/kill -KILL -- "-$recovery_pid" 2>/dev/null; '
                    f"/bin/rm -f {pid_path}"
                )
            try:
                stop = sandbox.execute_stream(stop_command, timeout_seconds=10, isolated=True, buffer_stdout=False)
                try:
                    stop.wait()
                finally:
                    stop.close()
            except Exception:
                logger.warning("sandbox_recovery_stop_failed", extra={"sandbox_id": sandbox.id}, exc_info=True)
            try:
                execution.close()
            except Exception:
                logger.warning("sandbox_recovery_stream_close_failed", extra={"sandbox_id": sandbox.id}, exc_info=True)
        stored = object_storage.head_object(storage_path)
        if not reader.finished or reader.size == 0 or stored is None or stored.get("ContentLength") != reader.size:
            raise RuntimeError("Workspace recovery upload is incomplete")
        TaskRun.update_state_atomic(
            run.id,
            updates={
                "sandbox_recovery_archive_sandbox_id": sandbox.id,
                "sandbox_recovery_archive_partial": reader.partial,
            },
        )

    @classmethod
    def download_url(cls, run: TaskRun) -> str | None:
        state = run.state or {}
        sandbox_id = state.get("sandbox_recovery_archive_sandbox_id")
        if not isinstance(sandbox_id, str) or sandbox_id != state.get("sandbox_retained_for_recovery"):
            return None
        storage_path = cls.storage_path(run, sandbox_id)
        if object_storage.head_object(storage_path) is None:
            return None
        filename = (
            "workspace-recovery-partial.tar.gz"
            if state.get("sandbox_recovery_archive_partial")
            else "workspace-recovery.tar.gz"
        )
        return object_storage.get_presigned_url(
            storage_path,
            content_type="application/gzip",
            content_disposition=f'attachment; filename="{filename}"',
        )
