from __future__ import annotations

import os
import json
import atexit
import base64
import signal
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.conf import settings
from django.utils import timezone

import structlog

from posthog.models import User
from posthog.redis import get_client

from products.notebooks.backend.models import KernelRuntime, Notebook
from products.tasks.backend.services.sandbox import (
    SandboxClass,
    SandboxConfig,
    SandboxProtocol,
    SandboxStatus,
    SandboxTemplate,
    get_sandbox_class_for_backend,
)

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
    lock_name: str
    started_at: datetime
    last_activity_at: datetime
    execution_count: int = 0
    backend: str = KernelRuntime.Backend.DOCKER
    sandbox_id: str | None = None


@dataclass
class _RedisLock:
    name: str
    timeout: float
    blocking_timeout: float
    _lock: Any | None = None

    def __enter__(self) -> _RedisLock:
        client = get_client()
        lock = client.lock(self.name, timeout=self.timeout, blocking_timeout=self.blocking_timeout)
        if not lock.acquire():
            raise RuntimeError(f"Failed to acquire Redis lock: {self.name}")
        self._lock = lock
        return self

    def __exit__(self, exc_type: Any, exc: Any, exc_tb: Any) -> None:
        if not self._lock:
            return
        with suppress(Exception):
            self._lock.release()


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


def build_notebook_sandbox_config(notebook: Notebook) -> SandboxConfig:
    sandbox_config = SandboxConfig(
        name=f"notebook-kernel-{notebook.short_id}",
        template=SandboxTemplate.NOTEBOOK_BASE,
    )
    if notebook.kernel_cpu_cores:
        sandbox_config.cpu_cores = notebook.kernel_cpu_cores
    if notebook.kernel_memory_gb:
        sandbox_config.memory_gb = notebook.kernel_memory_gb
    if notebook.kernel_idle_timeout_seconds:
        sandbox_config.ttl_seconds = notebook.kernel_idle_timeout_seconds
    return sandbox_config


class KernelRuntimeService:
    _TYPE_EXPRESSION_PREFIX = "__type__"
    _MODAL_REQUIRED_ENV_VARS = ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")
    _SERVICE_LOCK_TIMEOUT_SECONDS = 30.0
    _HANDLE_LOCK_TIMEOUT_SECONDS = 60.0
    _LOCK_BLOCKING_TIMEOUT_SECONDS = 10.0
    _EXECUTION_LOCK_TIMEOUT_BUFFER_SECONDS = 30.0

    def __init__(self, startup_timeout: float = 10.0, execution_timeout: float = 30.0):
        self._startup_timeout = startup_timeout
        self._execution_timeout = execution_timeout
        self._kernels: dict[str, _KernelHandle] = {}
        self._service_lock_name = "notebook-kernel-runtime-service"
        self._register_cleanup_hooks()

    def get_kernel_runtime(self, notebook: Notebook, user: User | None) -> KernelRuntimeSession:
        return KernelRuntimeSession(service=self, notebook=notebook, user=user)

    def ensure_kernel(self, notebook: Notebook, user: User | None) -> KernelRuntime:
        handle = self._ensure_handle(notebook, user)
        return handle.runtime

    def shutdown_kernel(self, notebook: Notebook, user: User | None) -> bool:
        with self._acquire_lock(self._service_lock_name, timeout=self._SERVICE_LOCK_TIMEOUT_SECONDS):
            handle = None
            for backend in (KernelRuntime.Backend.DOCKER, KernelRuntime.Backend.MODAL):
                key = self._get_kernel_key(notebook, user, backend)
                handle = self._kernels.pop(key, None)
                if handle:
                    break

        if not handle:
            runtime = (
                KernelRuntime.objects.filter(
                    team_id=notebook.team_id,
                    notebook_short_id=notebook.short_id,
                    user=user if isinstance(user, User) else None,
                    status__in=[KernelRuntime.Status.STARTING, KernelRuntime.Status.RUNNING],
                )
                .exclude(backend__isnull=True)
                .order_by("-last_used_at")
                .first()
            )
            if not runtime:
                return False
            handle = _KernelHandle(
                runtime=runtime,
                lock_name=self._kernel_lock_name(notebook, user, runtime.backend),
                started_at=runtime.created_at,
                last_activity_at=runtime.last_used_at,
                backend=runtime.backend,
                sandbox_id=runtime.sandbox_id,
            )

        with self._acquire_lock(handle.lock_name, timeout=self._HANDLE_LOCK_TIMEOUT_SECONDS):
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

        lock_timeout = (timeout or self._execution_timeout) + self._EXECUTION_LOCK_TIMEOUT_BUFFER_SECONDS
        with self._acquire_lock(handle.lock_name, timeout=lock_timeout):
            if not self._is_handle_alive(handle):
                handle = self._reset_handle(notebook, user, handle)

            if handle.backend in (KernelRuntime.Backend.MODAL, KernelRuntime.Backend.DOCKER):
                return self._execute_in_sandbox(
                    handle,
                    code,
                    capture_variables=capture_variables,
                    variable_names=valid_variable_names,
                    timeout=timeout,
                )

            raise RuntimeError("Unsupported notebook kernel backend.")

    def shutdown_all(self) -> None:
        with self._acquire_lock(self._service_lock_name, timeout=self._SERVICE_LOCK_TIMEOUT_SECONDS):
            handles = list(self._kernels.values())
            self._kernels.clear()

        for handle in handles:
            with self._acquire_lock(handle.lock_name, timeout=self._HANDLE_LOCK_TIMEOUT_SECONDS):
                self._shutdown_handle(handle, status=KernelRuntime.Status.DISCARDED)

    def _get_kernel_key(self, notebook: Notebook, user: User | None, backend: str) -> str:
        user_key = user.id if isinstance(user, User) else "anonymous"
        return f"{backend}:{notebook.team_id}:{notebook.short_id}:{user_key}"

    def _has_modal_credentials(self) -> bool:
        return all(os.environ.get(name, None) for name in self._MODAL_REQUIRED_ENV_VARS)

    def _get_sandbox_class(self, backend: str) -> SandboxClass:
        return get_sandbox_class_for_backend(backend)

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
        backend = self._get_backend(require_credentials=True)
        if backend is None:
            raise RuntimeError("Notebook sandbox provider is not configured.")
        key = self._get_kernel_key(notebook, user, backend)

        with self._acquire_lock(self._service_lock_name, timeout=self._SERVICE_LOCK_TIMEOUT_SECONDS):
            handle = self._kernels.get(key)

            if handle and self._is_handle_alive(handle):
                self._touch_runtime(handle, status_override=KernelRuntime.Status.RUNNING)
                return handle

            if handle:
                self._shutdown_handle(handle, status=KernelRuntime.Status.ERROR)

            handle = self._reuse_kernel_handle(notebook, user, backend)
            if handle:
                self._kernels[key] = handle
                return handle

            handle = self._create_kernel_handle(notebook, user, backend)

            self._kernels[key] = handle

        return handle

    def _reset_handle(self, notebook: Notebook, user: User | None, handle: _KernelHandle) -> _KernelHandle:
        self._shutdown_handle(handle, status=KernelRuntime.Status.ERROR)
        with self._acquire_lock(self._service_lock_name, timeout=self._SERVICE_LOCK_TIMEOUT_SECONDS):
            self._kernels.pop(self._get_kernel_key(notebook, user, handle.backend), None)
        return self._ensure_handle(notebook, user)

    def _shutdown_handle(self, handle: _KernelHandle, *, status: str) -> None:
        if handle.backend in (KernelRuntime.Backend.MODAL, KernelRuntime.Backend.DOCKER):
            if handle.sandbox_id:
                try:
                    sandbox_class = self._get_sandbox_class(handle.backend)
                    sandbox_class.get_by_id(handle.sandbox_id).destroy()
                except Exception:
                    logger.warning("notebook_kernel_sandbox_destroy_failed", kernel_runtime_id=str(handle.runtime.id))
            self._touch_runtime(handle, status_override=status)
            return

        self._touch_runtime(handle, status_override=status)

    def _touch_runtime(self, handle: _KernelHandle, *, status_override: str | None = None) -> None:
        runtime = handle.runtime
        runtime.last_used_at = timezone.now()
        if status_override:
            runtime.status = status_override
        runtime.save(update_fields=["last_used_at", "status"])

    def _is_handle_alive(self, handle: _KernelHandle) -> bool:
        if handle.backend in (KernelRuntime.Backend.MODAL, KernelRuntime.Backend.DOCKER):
            if not handle.sandbox_id:
                return False
            from products.tasks.backend.services.sandbox import SandboxStatus

            try:
                sandbox_class = self._get_sandbox_class(handle.backend)
                sandbox = sandbox_class.get_by_id(handle.sandbox_id)
            except Exception:
                return False
            return sandbox.get_status() == SandboxStatus.RUNNING

        return False

    def _reuse_kernel_handle(self, notebook: Notebook, user: User | None, backend: str) -> _KernelHandle | None:
        if backend not in (KernelRuntime.Backend.MODAL, KernelRuntime.Backend.DOCKER):
            return None
        return self._reuse_kernel_handle_for_backend(notebook, user, backend)

    def _mark_runtime_error(self, runtime: KernelRuntime, message: str) -> None:
        runtime.status = KernelRuntime.Status.ERROR
        runtime.last_error = message
        runtime.last_used_at = timezone.now()
        runtime.save(update_fields=["status", "last_error", "last_used_at"])

    def _create_runtime(self, notebook: Notebook, user: User | None, backend: str) -> KernelRuntime:
        self._discard_active_runtime(notebook, user, backend)
        notebook_reference = notebook if notebook.pk and not notebook._state.adding else None
        return KernelRuntime.objects.create(
            team_id=notebook.team_id,
            notebook=notebook_reference,
            notebook_short_id=notebook.short_id,
            user=user if isinstance(user, User) else None,
            status=KernelRuntime.Status.STARTING,
            backend=backend,
        )

    def _discard_active_runtime(self, notebook: Notebook, user: User | None, backend: str) -> None:
        active_statuses = [KernelRuntime.Status.STARTING, KernelRuntime.Status.RUNNING]
        KernelRuntime.objects.filter(
            team_id=notebook.team_id,
            notebook_short_id=notebook.short_id,
            user=user if isinstance(user, User) else None,
            status__in=active_statuses,
            backend=backend,
        ).update(status=KernelRuntime.Status.DISCARDED, last_used_at=timezone.now())

    def _get_backend(self, *, require_credentials: bool = False) -> str | None:
        provider = getattr(settings, "SANDBOX_PROVIDER", None)
        if provider is not None:
            if provider == KernelRuntime.Backend.MODAL and not self._has_modal_credentials():
                if require_credentials:
                    raise RuntimeError("Modal credentials are required to start notebook kernels in production.")
                logger.warning("notebook_kernel_modal_credentials_missing")
                return None
            return provider
        if settings.DEBUG or settings.TEST:
            return KernelRuntime.Backend.DOCKER
        return None

    def _create_kernel_handle(self, notebook: Notebook, user: User | None, backend: str) -> _KernelHandle:
        runtime = self._create_runtime(notebook, user, backend)
        connection_file = f"/tmp/jupyter/kernel-{runtime.id}.json"
        kernel_id = f"kernel-{runtime.id}"
        sandbox_config = build_notebook_sandbox_config(notebook)
        sandbox_class = self._get_sandbox_class(backend)
        sandbox = sandbox_class.create(sandbox_config)

        try:
            kernel_pid = self._start_kernel_process(sandbox, connection_file)
            self._wait_for_kernel_ready(sandbox, connection_file)
        except Exception as err:
            self._mark_runtime_error(runtime, "Failed to start kernel in sandbox")
            with suppress(Exception):
                sandbox.destroy()
            raise RuntimeError("Failed to start kernel in sandbox") from err

        runtime.kernel_id = kernel_id
        runtime.kernel_pid = kernel_pid
        runtime.connection_file = connection_file
        runtime.status = KernelRuntime.Status.RUNNING
        runtime.last_used_at = timezone.now()
        runtime.sandbox_id = sandbox.id
        runtime.save(
            update_fields=[
                "kernel_id",
                "kernel_pid",
                "connection_file",
                "status",
                "last_used_at",
                "sandbox_id",
            ]
        )

        return _KernelHandle(
            runtime=runtime,
            lock_name=self._kernel_lock_name(notebook, user, backend),
            started_at=timezone.now(),
            last_activity_at=timezone.now(),
            backend=backend,
            sandbox_id=sandbox.id,
        )

    def _start_kernel_process(self, sandbox: SandboxProtocol, connection_file: str) -> int:
        start_command = (
            "mkdir -p /tmp/jupyter && "
            f"nohup python3 -m ipykernel_launcher -f {connection_file} "
            "> /tmp/jupyter/kernel.log 2>&1 & echo $!"
        )
        start_result = sandbox.execute(start_command, timeout_seconds=int(self._startup_timeout))
        pid_line = start_result.stdout.strip().splitlines()[-1] if start_result.stdout else ""
        kernel_pid = int(pid_line) if pid_line.isdigit() else None
        if not kernel_pid:
            raise RuntimeError(f"Failed to start kernel process: {start_result.stdout} {start_result.stderr}")
        pid_check = sandbox.execute(f"ps -p {kernel_pid}", timeout_seconds=int(self._startup_timeout))
        if pid_check.exit_code != 0:
            raise RuntimeError(
                f"Kernel process exited immediately after startup: {pid_check.stdout} {pid_check.stderr}"
            )
        return kernel_pid

    def _wait_for_kernel_ready(self, sandbox: Any, connection_file: str) -> None:
        payload = {
            "connection_file": connection_file,
            "timeout": self._startup_timeout,
        }
        command = self._build_kernel_command(payload, action="ready")
        result = sandbox.execute(command, timeout_seconds=int(self._startup_timeout))
        if result.exit_code != 0:
            raise RuntimeError(f"Kernel did not become ready: {result.stdout} {result.stderr}")

    def _reuse_kernel_handle_for_backend(
        self, notebook: Notebook, user: User | None, backend: str
    ) -> _KernelHandle | None:
        runtime = (
            KernelRuntime.objects.filter(
                team_id=notebook.team_id,
                notebook_short_id=notebook.short_id,
                user=user if isinstance(user, User) else None,
                status=KernelRuntime.Status.RUNNING,
                backend=backend,
            )
            .exclude(connection_file__isnull=True)
            .exclude(connection_file="")
            .exclude(sandbox_id__isnull=True)
            .order_by("-last_used_at")
            .first()
        )

        if not runtime or not runtime.sandbox_id:
            return None

        try:
            sandbox_class = self._get_sandbox_class(backend)
            sandbox = sandbox_class.get_by_id(runtime.sandbox_id)
        except Exception:
            self._mark_runtime_error(runtime, "Sandbox not found")
            return None

        if sandbox.get_status() != SandboxStatus.RUNNING:
            self._mark_runtime_error(runtime, "Sandbox is not running")
            return None

        try:
            self._wait_for_kernel_ready(sandbox, runtime.connection_file or "")
        except Exception:
            self._mark_runtime_error(runtime, "Kernel not ready in sandbox")
            return None

        handle = _KernelHandle(
            runtime=runtime,
            lock_name=self._kernel_lock_name(notebook, user, backend),
            started_at=timezone.now(),
            last_activity_at=timezone.now(),
            execution_count=0,
            backend=backend,
            sandbox_id=runtime.sandbox_id,
        )
        self._touch_runtime(handle, status_override=KernelRuntime.Status.RUNNING)
        return handle

    def _build_kernel_command(self, payload: dict[str, Any], action: str) -> str:
        payload["action"] = action
        encoded_payload = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
        return (
            "python3 - <<'EOF_KERNEL_CMD_EXEC'\n"
            "import base64\n"
            "import json\n"
            "import os\n"
            "import sys\n"
            "import time\n"
            "import traceback\n"
            "from queue import Empty\n"
            "from jupyter_client import KernelManager\n"
            "from jupyter_client.blocking import BlockingKernelClient\n"
            "\n"
            f"payload = json.loads(base64.b64decode('{encoded_payload}').decode('utf-8'))\n"
            "action = payload.get('action')\n"
            "connection_file = payload.get('connection_file')\n"
            "timeout = payload.get('timeout', 30)\n"
            "code = payload.get('code')\n"
            "user_expressions = payload.get('user_expressions')\n"
            "\n"
            "start_time = time.monotonic()\n"
            "while not os.path.exists(connection_file):\n"
            "    if time.monotonic() - start_time >= timeout:\n"
            "        raise FileNotFoundError(connection_file)\n"
            "    time.sleep(0.1)\n"
            "\n"
            "client = None\n"
            "try:\n"
            "    manager = KernelManager(connection_file=connection_file)\n"
            "    manager.load_connection_file()\n"
            "    client = manager.blocking_client()\n"
            "    client.load_connection_file(connection_file)\n"
            "    client.start_channels()\n"
            "    client.wait_for_ready(timeout=timeout)\n"
            "    if action == 'ready':\n"
            "        print('ready')\n"
            "    else:\n"
            "        msg_id = client.execute(code, stop_on_error=False, user_expressions=user_expressions)\n"
            "        stdout = []\n"
            "        stderr = []\n"
            "        traceback_lines = []\n"
            "        result = None\n"
            "        status = 'ok'\n"
            "        execution_count = None\n"
            "        error_name = None\n"
            "        while True:\n"
            "            message = client.get_iopub_msg(timeout=timeout)\n"
            "            if message.get('parent_header', {}).get('msg_id') != msg_id:\n"
            "                continue\n"
            "            msg_type = message['header'].get('msg_type')\n"
            "            content = message.get('content', {})\n"
            "            if msg_type == 'status' and content.get('execution_state') == 'idle':\n"
            "                break\n"
            "            if msg_type == 'stream':\n"
            "                destination = stdout if content.get('name') == 'stdout' else stderr\n"
            "                destination.append(content.get('text', ''))\n"
            "                continue\n"
            "            if msg_type in ('execute_result', 'display_data'):\n"
            "                result = content.get('data') or result\n"
            "                execution_count = content.get('execution_count', execution_count)\n"
            "                continue\n"
            "            if msg_type == 'error':\n"
            "                status = 'error'\n"
            "                error_name = content.get('ename')\n"
            "                traceback_lines = content.get('traceback', [])\n"
            "        reply = None\n"
            "        try:\n"
            "            while True:\n"
            "                candidate = client.get_shell_msg(timeout=timeout)\n"
            "                if candidate.get('parent_header', {}).get('msg_id') == msg_id:\n"
            "                    reply = candidate\n"
            "                    break\n"
            "        except Empty:\n"
            "            reply = None\n"
            "        user_expressions_result = None\n"
            "        if reply:\n"
            "            reply_content = reply.get('content', {})\n"
            "            execution_count = reply_content.get('execution_count', execution_count)\n"
            "            status = reply_content.get('status', status)\n"
            "            if status == 'error' and not error_name:\n"
            "                error_name = reply_content.get('ename')\n"
            "                traceback_lines = reply_content.get('traceback', traceback_lines)\n"
            "            user_expressions_result = reply_content.get('user_expressions')\n"
            "        payload_out = {\n"
            "            'status': status,\n"
            "            'stdout': ''.join(stdout),\n"
            "            'stderr': ''.join(stderr),\n"
            "            'result': result,\n"
            "            'execution_count': execution_count,\n"
            "            'error_name': error_name,\n"
            "            'traceback': traceback_lines,\n"
            "            'user_expressions': user_expressions_result,\n"
            "        }\n"
            "        print(json.dumps(payload_out))\n"
            "except Empty:\n"
            "    print(json.dumps({'status': 'timeout', 'stdout': '', 'stderr': '', 'result': None, "
            "'execution_count': None, 'error_name': None, 'traceback': [], 'user_expressions': None}))\n"
            "except Exception as err:\n"
            "    print(json.dumps({\n"
            "        'status': 'error',\n"
            "        'stdout': '',\n"
            "        'stderr': str(err),\n"
            "        'result': None,\n"
            "        'execution_count': None,\n"
            "        'error_name': err.__class__.__name__,\n"
            "        'traceback': traceback.format_exception(type(err), err, err.__traceback__),\n"
            "        'user_expressions': None,\n"
            "    }))\n"
            "    sys.exit(1)\n"
            "finally:\n"
            "    if client:\n"
            "        client.stop_channels()\n"
            "EOF_KERNEL_CMD_EXEC"
        )

    def _kernel_lock_name(self, notebook: Notebook, user: User | None, backend: str) -> str:
        return f"notebook-kernel-runtime:{self._get_kernel_key(notebook, user, backend)}"

    def _acquire_lock(self, name: str, *, timeout: float) -> _RedisLock:
        return _RedisLock(
            name=name,
            timeout=timeout,
            blocking_timeout=self._LOCK_BLOCKING_TIMEOUT_SECONDS,
        )

    def _execute_in_sandbox(
        self,
        handle: _KernelHandle,
        code: str,
        *,
        capture_variables: bool,
        variable_names: list[str],
        timeout: float | None,
    ) -> KernelExecutionResult:
        if not handle.sandbox_id:
            raise RuntimeError("Sandbox not available for kernel execution.")

        timeout_seconds = int(timeout or self._execution_timeout)
        user_expressions: dict[str, str] | None = None
        if capture_variables and variable_names:
            user_expressions = {name: name for name in variable_names}
            user_expressions.update(
                {f"{self._TYPE_EXPRESSION_PREFIX}{name}": f"type({name}).__name__" for name in variable_names}
            )

        payload = {
            "connection_file": handle.runtime.connection_file,
            "timeout": timeout_seconds,
            "code": code,
            "user_expressions": user_expressions,
        }
        command = self._build_kernel_command(payload, action="execute")
        sandbox_class = self._get_sandbox_class(handle.backend)
        sandbox = sandbox_class.get_by_id(handle.sandbox_id)
        started_at = timezone.now()
        result = sandbox.execute(command, timeout_seconds=timeout_seconds)
        if result.exit_code != 0:
            raise RuntimeError(f"Kernel execution failed: {result.stdout} {result.stderr}")

        lines = result.stdout.strip().splitlines()
        if not lines:
            raise RuntimeError("Kernel execution returned no output.")

        try:
            payload_out = json.loads(lines[-1])
        except json.JSONDecodeError as err:
            raise RuntimeError(f"Failed to parse kernel execution output: {result.stdout}") from err

        status = payload_out.get("status", "error")
        execution_count = payload_out.get("execution_count")
        error_name = payload_out.get("error_name")
        traceback = payload_out.get("traceback", [])
        variables = None
        if user_expressions is not None:
            variables = self._parse_user_expressions(payload_out.get("user_expressions"))

        handle.execution_count = execution_count or handle.execution_count
        handle.last_activity_at = timezone.now()
        self._touch_runtime(handle, status_override=KernelRuntime.Status.RUNNING)

        return KernelExecutionResult(
            status=status,
            stdout=payload_out.get("stdout", ""),
            stderr=payload_out.get("stderr", ""),
            result=payload_out.get("result"),
            execution_count=execution_count,
            error_name=error_name,
            traceback=traceback,
            variables=variables,
            started_at=started_at,
            completed_at=timezone.now(),
            kernel_runtime=handle.runtime,
        )


notebook_kernel_runtime_service = KernelRuntimeService()


def get_kernel_runtime(notebook: Notebook, user: User | None) -> KernelRuntimeSession:
    return notebook_kernel_runtime_service.get_kernel_runtime(notebook, user)
