from __future__ import annotations

import os
import atexit
import signal
import threading
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from queue import Empty
from typing import Any

from django.conf import settings
from django.utils import timezone

import structlog
from jupyter_client import KernelManager
from jupyter_client.blocking import BlockingKernelClient

from posthog.models import User

from products.notebooks.backend.models import KernelRuntime, Notebook

logger = structlog.get_logger(__name__)


@dataclass
class KernelExecutionResult:
    status: str
    stdout: str
    stderr: str
    result: dict[str, Any] | None
    execution_count: int | None
    error_name: str | None
    traceback: list[str]
    variables: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime
    kernel_runtime: KernelRuntime

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "result": self.result,
            "execution_count": self.execution_count,
            "error_name": self.error_name,
            "traceback": self.traceback,
            "variables": self.variables,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "kernel_runtime": {
                "id": str(self.kernel_runtime.id),
                "status": self.kernel_runtime.status,
                "last_used_at": self.kernel_runtime.last_used_at,
            },
        }


@dataclass
class _KernelHandle:
    runtime: KernelRuntime
    manager: KernelManager
    client: BlockingKernelClient
    lock: threading.RLock
    started_at: datetime
    last_activity_at: datetime
    execution_count: int = 0


@dataclass
class KernelRuntimeSession:
    service: KernelRuntimeService
    notebook: Notebook
    user: User | None

    def ensure(self) -> KernelRuntime:
        return self.service.ensure_kernel(self.notebook, self.user)

    def shutdown(self) -> bool:
        return self.service.shutdown_kernel(self.notebook, self.user)

    def restart(self) -> KernelRuntime:
        return self.service.restart_kernel(self.notebook, self.user)

    def execute(
        self,
        code: str,
        *,
        capture_variables: bool = True,
        variable_names: list[str] | None = None,
        timeout: float | None = None,
    ) -> KernelExecutionResult:
        return self.service.execute(
            self.notebook,
            self.user,
            code,
            capture_variables=capture_variables,
            variable_names=variable_names,
            timeout=timeout,
        )


class KernelRuntimeService:
    _TYPE_EXPRESSION_PREFIX = "__type__"

    def __init__(self, startup_timeout: float = 10.0, execution_timeout: float = 30.0):
        self._startup_timeout = startup_timeout
        self._execution_timeout = execution_timeout
        self._kernels: dict[str, _KernelHandle] = {}
        self._service_lock = threading.RLock()
        self._register_cleanup_hooks()

    def get_kernel_runtime(self, notebook: Notebook, user: User | None) -> KernelRuntimeSession:
        return KernelRuntimeSession(service=self, notebook=notebook, user=user)

    def ensure_kernel(self, notebook: Notebook, user: User | None) -> KernelRuntime:
        handle = self._ensure_handle(notebook, user)
        return handle.runtime

    def shutdown_kernel(self, notebook: Notebook, user: User | None) -> bool:
        key = self._get_kernel_key(notebook, user)

        with self._service_lock:
            handle = self._kernels.pop(key, None)

        if not handle:
            return False

        with handle.lock:
            self._shutdown_handle(handle, status=KernelRuntime.Status.STOPPED)

        return True

    def restart_kernel(self, notebook: Notebook, user: User | None) -> KernelRuntime:
        self.shutdown_kernel(notebook, user)
        handle = self._ensure_handle(notebook, user)
        return handle.runtime

    def execute(
        self,
        notebook: Notebook,
        user: User | None,
        code: str,
        *,
        capture_variables: bool = True,
        variable_names: list[str] | None = None,
        timeout: float | None = None,
    ) -> KernelExecutionResult:
        valid_variable_names = [name for name in (variable_names or []) if name.isidentifier()]
        user_expressions: dict[str, str] | None = None
        if capture_variables and valid_variable_names:
            user_expressions = {}
            for name in valid_variable_names:
                user_expressions[name] = name
                user_expressions[f"{self._TYPE_EXPRESSION_PREFIX}{name}"] = f"type({name}).__name__"
        handle = self._ensure_handle(notebook, user)

        with handle.lock:
            if not handle.manager.is_alive():
                handle = self._reset_handle(notebook, user, handle)

            timeout_seconds = timeout or self._execution_timeout
            started_at = timezone.now()
            stdout: list[str] = []
            stderr: list[str] = []
            traceback: list[str] = []
            result: dict[str, Any] | None = None
            status = "ok"
            execution_count: int | None = None
            error_name: str | None = None
            variables: dict[str, Any] | None = None

            msg_id = handle.client.execute(
                code,
                stop_on_error=False,
                user_expressions=user_expressions,
            )

            try:
                while True:
                    message = handle.client.get_iopub_msg(timeout=timeout_seconds)

                    if message.get("parent_header", {}).get("msg_id") != msg_id:
                        continue

                    msg_type = message["header"].get("msg_type")
                    content = message.get("content", {})

                    if msg_type == "status" and content.get("execution_state") == "idle":
                        break

                    if msg_type == "stream":
                        destination = stdout if content.get("name") == "stdout" else stderr
                        destination.append(content.get("text", ""))
                        continue

                    if msg_type in ("execute_result", "display_data"):
                        result = content.get("data") or result
                        execution_count = content.get("execution_count", execution_count)
                        continue

                    if msg_type == "error":
                        status = "error"
                        error_name = content.get("ename")
                        traceback = content.get("traceback", [])

            except Empty:
                status = "timeout"

            reply = None
            try:
                while True:
                    candidate = handle.client.get_shell_msg(timeout=timeout_seconds)
                    if candidate.get("parent_header", {}).get("msg_id") == msg_id:
                        reply = candidate
                        break
            except Empty:
                reply = None

            if reply:
                reply_content = reply.get("content", {})
                execution_count = reply_content.get("execution_count", execution_count)
                status = reply_content.get("status", status)

                if status == "error" and not error_name:
                    error_name = reply_content.get("ename")
                    traceback = reply_content.get("traceback", traceback)
                if user_expressions:
                    variables = self._parse_user_expressions(reply_content.get("user_expressions", {}))

            handle.execution_count = execution_count or handle.execution_count
            handle.last_activity_at = timezone.now()
            self._touch_runtime(handle, status_override=KernelRuntime.Status.RUNNING)

            return KernelExecutionResult(
                status=status,
                stdout="".join(stdout),
                stderr="".join(stderr),
                result=result,
                execution_count=execution_count,
                error_name=error_name,
                traceback=traceback,
                variables=variables,
                started_at=started_at,
                completed_at=timezone.now(),
                kernel_runtime=handle.runtime,
            )

    def shutdown_all(self) -> None:
        with self._service_lock:
            handles = list(self._kernels.values())
            self._kernels.clear()

        for handle in handles:
            with handle.lock:
                self._shutdown_handle(handle, status=KernelRuntime.Status.DISCARDED)

    def _get_kernel_key(self, notebook: Notebook, user: User | None) -> str:
        user_key = user.id if isinstance(user, User) else "anonymous"
        return f"{notebook.team_id}:{notebook.short_id}:{user_key}"

    def _ensure_debug(self) -> None:
        if not settings.DEBUG or os.getenv("DEBUG") != "1":
            raise RuntimeError("Notebook kernels are only available in DEBUG for now.")

    def _parse_user_expressions(self, user_expressions: Any) -> dict[str, Any] | None:
        if not isinstance(user_expressions, dict):
            return None

        parsed: dict[str, Any] = {}
        type_results: dict[str, str] = {}
        for name, payload in user_expressions.items():
            if not isinstance(payload, dict):
                continue
            if name.startswith(self._TYPE_EXPRESSION_PREFIX):
                variable_name = name[len(self._TYPE_EXPRESSION_PREFIX) :]
                if not variable_name:
                    continue
                if payload.get("status") == "ok":
                    type_name = self._normalize_type_name(self._extract_user_expression_text(payload))
                    if type_name:
                        type_results[variable_name] = type_name
                continue
            status = payload.get("status")
            if status == "ok":
                parsed[name] = {
                    "status": "ok",
                }
            else:
                parsed[name] = {
                    "status": "error",
                    "ename": payload.get("ename"),
                    "evalue": payload.get("evalue"),
                    "traceback": payload.get("traceback", []),
                }
        for name, payload in parsed.items():
            type_name = type_results.get(name)
            if type_name and payload.get("status") == "ok":
                payload["type"] = type_name
        return parsed or None

    def _extract_user_expression_text(self, payload: dict[str, Any]) -> str | None:
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        preferred = data.get("text/plain") or data.get("text/html")
        if isinstance(preferred, str):
            return preferred
        return None

    def _normalize_type_name(self, value: str | None) -> str | None:
        if not value:
            return None
        stripped = value.strip()
        if len(stripped) >= 2 and (
            (stripped.startswith("'") and stripped.endswith("'"))
            or (stripped.startswith('"') and stripped.endswith('"'))
        ):
            stripped = stripped[1:-1]
        return stripped or None

    def _register_cleanup_hooks(self) -> None:
        def _cleanup(*_: Any) -> None:
            self.shutdown_all()

        atexit.register(_cleanup)

        for sig in (signal.SIGTERM, signal.SIGINT):
            previous = signal.getsignal(sig)

            def _handler(signum: int, frame: Any, previous_handler: Any = previous) -> None:
                _cleanup()
                if callable(previous_handler):
                    previous_handler(signum, frame)

            try:
                signal.signal(sig, _handler)
            except ValueError:
                logger.warning("notebook_kernels_signal_registration_failed", signal=sig)

    def _ensure_handle(self, notebook: Notebook, user: User | None) -> _KernelHandle:
        self._ensure_debug()
        key = self._get_kernel_key(notebook, user)

        with self._service_lock:
            handle = self._kernels.get(key)

            if handle and self._is_handle_alive(handle):
                self._touch_runtime(handle, status_override=KernelRuntime.Status.RUNNING)
                return handle

            if handle:
                self._shutdown_handle(handle, status=KernelRuntime.Status.ERROR)

            handle = self._reuse_kernel_handle(notebook, user)
            if handle:
                self._kernels[key] = handle
                return handle

            runtime = self._create_runtime(notebook, user)
            manager = KernelManager(kernel_name="python3")

            try:
                manager.start_kernel()
                client = manager.blocking_client()
                client.start_channels()
                client.wait_for_ready(timeout=self._startup_timeout)
            except Exception as err:
                logger.exception("notebook_kernel_start_failed", notebook_short_id=notebook.short_id)
                with suppress(Exception):
                    manager.shutdown_kernel(now=True)
                self._mark_runtime_error(runtime, "Failed to start kernel")
                raise RuntimeError("Failed to start kernel") from err

            runtime.kernel_id = manager.kernel_id
            kernel_process = getattr(manager, "kernel", None)
            runtime.kernel_pid = kernel_process.pid if kernel_process else None
            runtime.connection_file = manager.connection_file
            runtime.status = KernelRuntime.Status.RUNNING
            runtime.last_used_at = timezone.now()
            runtime.save(update_fields=["kernel_id", "kernel_pid", "connection_file", "status", "last_used_at"])

            handle = _KernelHandle(
                runtime=runtime,
                manager=manager,
                client=client,
                lock=threading.RLock(),
                started_at=timezone.now(),
                last_activity_at=timezone.now(),
            )
            self._kernels[key] = handle

        return handle

    def _reset_handle(self, notebook: Notebook, user: User | None, handle: _KernelHandle) -> _KernelHandle:
        self._shutdown_handle(handle, status=KernelRuntime.Status.ERROR)
        with self._service_lock:
            self._kernels.pop(self._get_kernel_key(notebook, user), None)
        return self._ensure_handle(notebook, user)

    def _shutdown_handle(self, handle: _KernelHandle, *, status: str) -> None:
        try:
            handle.client.stop_channels()
        except Exception:
            logger.warning("notebook_kernel_stop_channels_failed", kernel_runtime_id=str(handle.runtime.id))

        try:
            handle.manager.shutdown_kernel(now=True)
        except Exception:
            logger.warning("notebook_kernel_shutdown_failed", kernel_runtime_id=str(handle.runtime.id))

        self._touch_runtime(handle, status_override=status)

    def _touch_runtime(self, handle: _KernelHandle, *, status_override: str | None = None) -> None:
        runtime = handle.runtime
        runtime.last_used_at = timezone.now()
        if status_override:
            runtime.status = status_override
        runtime.save(update_fields=["last_used_at", "status"])

    def _is_handle_alive(self, handle: _KernelHandle) -> bool:
        if self._is_process_running(handle.runtime.kernel_pid):
            return True
        return handle.manager.is_alive()

    def _is_process_running(self, pid: int | None) -> bool:
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _reuse_kernel_handle(self, notebook: Notebook, user: User | None) -> _KernelHandle | None:
        runtime = (
            KernelRuntime.objects.filter(
                team_id=notebook.team_id,
                notebook_short_id=notebook.short_id,
                user=user if isinstance(user, User) else None,
                status=KernelRuntime.Status.RUNNING,
            )
            .exclude(connection_file__isnull=True)
            .exclude(connection_file="")
            .order_by("-last_used_at")
            .first()
        )

        if not runtime:
            return None

        if runtime.kernel_pid and not self._is_process_running(runtime.kernel_pid):
            self._mark_runtime_error(runtime, "Kernel process is not running")
            return None

        manager = KernelManager(connection_file=runtime.connection_file)
        client = manager.blocking_client()
        try:
            manager.load_connection_file()
            client.load_connection_file(runtime.connection_file)
            client.start_channels()
            client.wait_for_ready(timeout=self._startup_timeout)
        except Exception:
            logger.exception(
                "notebook_kernel_reconnect_failed",
                notebook_short_id=notebook.short_id,
                kernel_runtime_id=str(runtime.id),
            )
            with suppress(Exception):
                client.stop_channels()
            self._mark_runtime_error(runtime, "Failed to reconnect to kernel")
            return None

        handle = _KernelHandle(
            runtime=runtime,
            manager=manager,
            client=client,
            lock=threading.RLock(),
            started_at=timezone.now(),
            last_activity_at=timezone.now(),
            execution_count=0,
        )
        self._touch_runtime(handle, status_override=KernelRuntime.Status.RUNNING)
        return handle

    def _mark_runtime_error(self, runtime: KernelRuntime, message: str) -> None:
        runtime.status = KernelRuntime.Status.ERROR
        runtime.last_error = message
        runtime.last_used_at = timezone.now()
        runtime.save(update_fields=["status", "last_error", "last_used_at"])

    def _create_runtime(self, notebook: Notebook, user: User | None) -> KernelRuntime:
        self._discard_active_runtime(notebook, user)
        return KernelRuntime.objects.create(
            team_id=notebook.team_id,
            notebook=notebook if notebook.pk else None,
            notebook_short_id=notebook.short_id,
            user=user if isinstance(user, User) else None,
            status=KernelRuntime.Status.STARTING,
        )

    def _discard_active_runtime(self, notebook: Notebook, user: User | None) -> None:
        active_statuses = [KernelRuntime.Status.STARTING, KernelRuntime.Status.RUNNING]
        KernelRuntime.objects.filter(
            team_id=notebook.team_id,
            notebook_short_id=notebook.short_id,
            user=user if isinstance(user, User) else None,
            status__in=active_statuses,
        ).update(status=KernelRuntime.Status.DISCARDED, last_used_at=timezone.now())


notebook_kernel_runtime_service = KernelRuntimeService()


def get_kernel_runtime(notebook: Notebook, user: User | None) -> KernelRuntimeSession:
    return notebook_kernel_runtime_service.get_kernel_runtime(notebook, user)
