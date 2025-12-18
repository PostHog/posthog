from __future__ import annotations

import ast
import uuid
import atexit
import signal
import threading
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from queue import Empty
from typing import Any

from django.utils import timezone

import structlog
from jupyter_client import KernelManager
from jupyter_client.blocking import BlockingKernelClient

from products.notebooks.backend.models import Notebook

logger = structlog.get_logger(__name__)

HOGQL_BOOTSTRAP_CODE = """
from posthog.hogql.parser import parse_expr as _posthog_parse_expr
globals()["parse_expr"] = _posthog_parse_expr
"""


@dataclass
class KernelStatus:
    id: str
    notebook_short_id: str
    started_at: datetime
    last_activity_at: datetime
    execution_count: int
    alive: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "notebook_short_id": self.notebook_short_id,
            "started_at": self.started_at,
            "last_activity_at": self.last_activity_at,
            "execution_count": self.execution_count,
            "alive": self.alive,
        }


@dataclass
class KernelExecutionResult:
    status: str
    stdout: str
    stderr: str
    result: dict[str, Any] | None
    variables: dict[str, str]
    execution_count: int | None
    error_name: str | None
    traceback: list[str]
    started_at: datetime
    completed_at: datetime
    kernel: KernelStatus

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "result": self.result,
            "variables": self.variables,
            "execution_count": self.execution_count,
            "error_name": self.error_name,
            "traceback": self.traceback,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "kernel": self.kernel.as_dict(),
        }


@dataclass
class _KernelHandle:
    id: str
    notebook_short_id: str
    manager: KernelManager
    client: BlockingKernelClient
    lock: threading.RLock
    started_at: datetime
    last_activity_at: datetime
    execution_count: int = 0
    initialized: bool = False

    @property
    def status(self) -> KernelStatus:
        return KernelStatus(
            id=self.id,
            notebook_short_id=self.notebook_short_id,
            started_at=self.started_at,
            last_activity_at=self.last_activity_at,
            execution_count=self.execution_count,
            alive=self.manager.is_alive(),
        )


class NotebookKernelService:
    def __init__(self, startup_timeout: float = 10.0, execution_timeout: float = 30.0):
        self._startup_timeout = startup_timeout
        self._execution_timeout = execution_timeout
        self._kernels: dict[str, _KernelHandle] = {}
        self._service_lock = threading.RLock()
        self._register_cleanup_hooks()

    def _get_kernel_key(self, notebook: Notebook) -> str:
        return f"{notebook.team_id}:{notebook.short_id}"

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

    def ensure_kernel(self, notebook: Notebook) -> KernelStatus:
        handle = self._ensure_handle(notebook)
        return handle.status

    def shutdown_kernel(self, notebook: Notebook) -> bool:
        key = self._get_kernel_key(notebook)

        with self._service_lock:
            handle = self._kernels.pop(key, None)

        if not handle:
            return False

        with handle.lock:
            self._shutdown_handle(handle)

        return True

    def shutdown_all(self) -> None:
        with self._service_lock:
            handles = list(self._kernels.values())
            self._kernels.clear()

        for handle in handles:
            with handle.lock:
                self._shutdown_handle(handle)

    def restart_kernel(self, notebook: Notebook) -> KernelStatus:
        self.shutdown_kernel(notebook)
        handle = self._ensure_handle(notebook)
        return handle.status

    def execute(
        self,
        notebook: Notebook,
        code: str,
        *,
        capture_variables: bool = True,
        timeout: float | None = None,
    ) -> KernelExecutionResult:
        handle = self._ensure_handle(notebook)

        with handle.lock:
            if not handle.manager.is_alive():
                handle = self._reset_handle(notebook, handle)

            timeout_seconds = timeout or self._execution_timeout
            started_at = timezone.now()
            stdout: list[str] = []
            stderr: list[str] = []
            traceback: list[str] = []
            result: dict[str, Any] | None = None
            variables: dict[str, str] = {}
            status = "ok"
            execution_count: int | None = None
            error_name: str | None = None

            expression_key = "__posthog_variables__"
            msg_id = handle.client.execute(
                code,
                stop_on_error=False,
                user_expressions={
                    expression_key: "{k: repr(v) for k, v in locals().items() if not k.startswith('_')}",
                }
                if capture_variables
                else None,
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

                if capture_variables:
                    variables = self._parse_variables(reply_content.get("user_expressions", {}), expression_key)

                if status == "error" and not error_name:
                    error_name = reply_content.get("ename")
                    traceback = reply_content.get("traceback", traceback)

            handle.execution_count = execution_count or handle.execution_count
            handle.last_activity_at = timezone.now()

            return KernelExecutionResult(
                status=status,
                stdout="".join(stdout),
                stderr="".join(stderr),
                result=result,
                variables=variables,
                execution_count=execution_count,
                error_name=error_name,
                traceback=traceback,
                started_at=started_at,
                completed_at=timezone.now(),
                kernel=handle.status,
            )

    def _parse_variables(self, user_expressions: dict[str, Any], expression_key: str) -> dict[str, str]:
        expression = user_expressions.get(expression_key)
        if not expression or expression.get("status") != "ok":
            return {}

        data = expression.get("data", {})
        text_value = data.get("text/plain")
        if not isinstance(text_value, str):
            return {}

        try:
            parsed = ast.literal_eval(text_value)
        except Exception:
            logger.warning("notebook_kernel_variables_parse_failed")
            return {}

        return {k: str(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}

    def _ensure_handle(self, notebook: Notebook) -> _KernelHandle:
        key = self._get_kernel_key(notebook)

        with self._service_lock:
            handle = self._kernels.get(key)

            if handle and handle.manager.is_alive():
                pass
            else:
                if handle:
                    self._shutdown_handle(handle)

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
                    raise RuntimeError("Failed to start kernel") from err

                handle = _KernelHandle(
                    id=uuid.uuid4().hex,
                    notebook_short_id=notebook.short_id,
                    manager=manager,
                    client=client,
                    lock=threading.RLock(),
                    started_at=timezone.now(),
                    last_activity_at=timezone.now(),
                )
                self._kernels[key] = handle

        self._initialize_handle(handle)
        return handle

    def _reset_handle(self, notebook: Notebook, handle: _KernelHandle) -> _KernelHandle:
        self._shutdown_handle(handle)
        with self._service_lock:
            self._kernels.pop(self._get_kernel_key(notebook), None)
        return self._ensure_handle(notebook)

    def _initialize_handle(self, handle: _KernelHandle) -> None:
        if handle.initialized:
            return

        with handle.lock:
            if handle.initialized:
                return

            success = self._run_setup_code(handle, HOGQL_BOOTSTRAP_CODE)
            handle.initialized = success
            handle.last_activity_at = timezone.now()

    def _run_setup_code(self, handle: _KernelHandle, code: str) -> bool:
        msg_id = handle.client.execute(
            code,
            silent=True,
            store_history=False,
            stop_on_error=False,
        )

        status: str | None = None

        try:
            while True:
                message = handle.client.get_iopub_msg(timeout=self._startup_timeout)

                if message.get("parent_header", {}).get("msg_id") != msg_id:
                    continue

                msg_type = message["header"].get("msg_type")
                content = message.get("content", {})

                if msg_type == "status" and content.get("execution_state") == "idle":
                    break

                if msg_type == "error":
                    status = "error"
        except Empty:
            status = "timeout"

        try:
            while True:
                reply = handle.client.get_shell_msg(timeout=self._startup_timeout)
                if reply.get("parent_header", {}).get("msg_id") == msg_id:
                    reply_content = reply.get("content", {})
                    status = reply_content.get("status", status)
                    break
        except Empty:
            status = status or "timeout"

        if status and status != "ok":
            logger.warning("notebook_kernel_setup_code_failed", kernel_id=handle.id, status=status)

        return status in (None, "ok")

    def _shutdown_handle(self, handle: _KernelHandle) -> None:
        try:
            handle.client.stop_channels()
        except Exception:
            logger.warning("notebook_kernel_stop_channels_failed", kernel_id=handle.id)

        try:
            handle.manager.shutdown_kernel(now=True)
        except Exception:
            logger.warning("notebook_kernel_shutdown_failed", kernel_id=handle.id)


notebook_kernel_service = NotebookKernelService()
