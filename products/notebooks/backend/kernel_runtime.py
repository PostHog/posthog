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

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team, User
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
    media: list[dict[str, Any]]
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
            "media": self.media,
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
                "sandbox_id": self.kernel_runtime.sandbox_id,
            },
        }


@dataclass
class _NotebookBridgeParser:
    marker: str
    buffer: str = ""

    def feed(self, text: str) -> tuple[str, list[str]]:
        self.buffer += text
        output_parts: list[str] = []
        payloads: list[str] = []
        while True:
            newline_index = self.buffer.find("\n")
            if newline_index == -1:
                break

            line = self.buffer[: newline_index + 1]
            self.buffer = self.buffer[newline_index + 1 :]
            line_content = line[:-1]

            if not line_content.startswith(self.marker):
                output_parts.append(line)
                continue

            size_start = len(self.marker)
            size_end = size_start
            while size_end < len(line_content) and line_content[size_end].isdigit():
                size_end += 1

            if size_end == size_start or size_end >= len(line_content):
                output_parts.append(line)
                continue

            if line_content[size_end] != " ":
                output_parts.append(line)
                continue

            size = int(line_content[size_start:size_end])
            payload_start = size_end + 1
            payload_end = payload_start + size
            if payload_end != len(line_content):
                output_parts.append(line)
                continue

            payloads.append(line_content[payload_start:payload_end])

        if self.buffer and not self.buffer.startswith(self.marker) and not self.marker.startswith(self.buffer):
            output_parts.append(self.buffer)
            self.buffer = ""

        return "".join(output_parts), payloads

    def flush(self) -> str:
        remaining = self.buffer
        self.buffer = ""
        return remaining


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

    def execute_stream(
        self,
        code: str,
        *,
        capture_variables: bool = True,
        variable_names: list[str] | None = None,
        timeout: float | None = None,
    ):
        return self.service.execute_stream(
            self.notebook,
            self.user,
            code,
            capture_variables=capture_variables,
            variable_names=variable_names,
            timeout=timeout,
        )

    def dataframe_page(
        self,
        variable_name: str,
        *,
        offset: int = 0,
        limit: int = 20,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return self.service.dataframe_page(
            self.notebook,
            self.user,
            variable_name,
            offset=offset,
            limit=limit,
            timeout=timeout,
        )


def build_notebook_sandbox_config(notebook: Notebook) -> SandboxConfig:
    sandbox_config = SandboxConfig(
        name=f"notebook-kernel-{notebook.short_id}",
        template=SandboxTemplate.NOTEBOOK_BASE,
        cpu_cores=1,
        memory_gb=2,
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
    _HOGQL_QUERY_EXPRESSION_PREFIX = "__hogql_query__"
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

    def execute_stream(
        self,
        notebook: Notebook,
        user: User | None,
        code: str,
        *,
        capture_variables: bool = True,
        variable_names: list[str] | None = None,
        timeout: float | None = None,
    ):
        valid_variable_names = [name for name in (variable_names or []) if name.isidentifier()]
        handle = self._ensure_handle(notebook, user)
        lock_timeout = (timeout or self._execution_timeout) + self._EXECUTION_LOCK_TIMEOUT_BUFFER_SECONDS

        def _stream():
            with self._acquire_lock(handle.lock_name, timeout=lock_timeout):
                current_handle = handle
                if not self._is_handle_alive(current_handle):
                    current_handle = self._reset_handle(notebook, user, current_handle)

                if current_handle.backend in (KernelRuntime.Backend.MODAL, KernelRuntime.Backend.DOCKER):
                    yield from self._execute_in_sandbox_stream(
                        current_handle,
                        code,
                        capture_variables=capture_variables,
                        variable_names=valid_variable_names,
                        timeout=timeout,
                    )
                    return

                raise RuntimeError("Unsupported notebook kernel backend.")

        return _stream()

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
        type_errors: dict[str, dict[str, Any]] = {}
        query_results: dict[str, str] = {}
        query_errors: dict[str, dict[str, Any]] = {}
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
                elif payload.get("status") == "error":
                    type_errors[variable_name] = {
                        "status": "error",
                        "ename": payload.get("ename"),
                        "evalue": payload.get("evalue"),
                        "traceback": payload.get("traceback", []),
                    }
                continue
            if name.startswith(self._HOGQL_QUERY_EXPRESSION_PREFIX):
                variable_name = name[len(self._HOGQL_QUERY_EXPRESSION_PREFIX) :]
                if not variable_name:
                    continue
                if payload.get("status") == "ok":
                    query_value = self._normalize_user_expression_string(self._extract_user_expression_text(payload))
                    if query_value:
                        query_results[variable_name] = query_value
                elif payload.get("status") == "error":
                    query_errors[variable_name] = {
                        "status": "error",
                        "ename": payload.get("ename"),
                        "evalue": payload.get("evalue"),
                        "traceback": payload.get("traceback", []),
                    }
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
            query_value = query_results.get(name)
            if query_value and payload.get("status") == "ok":
                payload["hogql_query"] = query_value
        for name, error_payload in type_errors.items():
            if name not in parsed:
                parsed[name] = error_payload
        for name, type_name in type_results.items():
            if name not in parsed:
                entry: dict[str, Any] = {"status": "ok", "type": type_name}
                query_value = query_results.get(name)
                if query_value:
                    entry["hogql_query"] = query_value
                parsed[name] = entry
        for name, error_payload in query_errors.items():
            if name not in parsed:
                parsed[name] = error_payload
        return parsed or None

    def _notebook_bridge_marker(self, handle: _KernelHandle) -> str:
        sandbox_id = handle.sandbox_id or "unknown"
        return f"__NOTEBOOK_BRIDGE_{sandbox_id}__"

    def _strip_notebook_bridge_messages(self, text: str, marker: str) -> str:
        parser = _NotebookBridgeParser(marker=marker)
        filtered, _ = parser.feed(text)
        return filtered + parser.flush()

    def _parse_hogql_placeholders_payload(self, payload: Any) -> dict[str, ast.Expr] | None:
        if not isinstance(payload, dict):
            return None
        placeholders: dict[str, ast.Expr] = {}
        for name, entry in payload.items():
            if not isinstance(name, str) or not isinstance(entry, dict):
                continue
            placeholder_type = entry.get("type")
            if placeholder_type == "hogql_query":
                query = entry.get("query")
                if isinstance(query, str) and query.strip():
                    placeholders[name] = parse_select(query)
            elif placeholder_type == "constant":
                if "value" in entry:
                    placeholders[name] = ast.Constant(value=entry.get("value"))
        return placeholders or None

    def _handle_notebook_bridge_payload(self, payload_json: str, handle: _KernelHandle) -> None:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            logger.warning(
                "notebook_bridge_payload_invalid",
                payload=payload_json[:200],
                sandbox_id=handle.sandbox_id,
            )
            return

        call = payload.get("call") or "hogql_execute"
        query = payload.get("query")
        response_path = payload.get("response_path")
        placeholders_payload = payload.get("placeholders")
        if (
            not isinstance(call, str)
            or not isinstance(query, str)
            or not isinstance(response_path, str)
            or not response_path
        ):
            logger.warning(
                "notebook_bridge_payload_missing_fields",
                payload=payload,
                sandbox_id=handle.sandbox_id,
            )
            return

        if not handle.sandbox_id:
            logger.warning(
                "notebook_bridge_missing_sandbox",
                sandbox_id=handle.sandbox_id,
                team_id=handle.runtime.team_id,
            )
            return

        try:
            team = Team.objects.get(id=handle.runtime.team_id)
        except Team.DoesNotExist:
            logger.warning(
                "notebook_bridge_team_missing",
                team_id=handle.runtime.team_id,
                sandbox_id=handle.sandbox_id,
            )
            return

        if call != "hogql_execute":
            logger.warning(
                "notebook_bridge_unsupported_call",
                call=call,
                sandbox_id=handle.sandbox_id,
                team_id=handle.runtime.team_id,
            )
            response_payload = {"error": f"Unsupported notebook bridge call: {call}"}
        else:
            try:
                placeholders = self._parse_hogql_placeholders_payload(placeholders_payload)
                response = execute_hogql_query(query=query, team=team, placeholders=placeholders)
                if hasattr(response, "model_dump"):
                    response_payload = response.model_dump(exclude_none=True)
                else:
                    response_payload = response.dict(exclude_none=True)
                if "clickhouse" in response_payload:
                    del response_payload["clickhouse"]
                if "hogql" in response_payload:
                    del response_payload["hogql"]
                if "timings" in response_payload:
                    del response_payload["timings"]
                if "modifiers" in response_payload:
                    del response_payload["modifiers"]
            except Exception as err:
                logger.exception(
                    "notebook_bridge_query_failed",
                    sandbox_id=handle.sandbox_id,
                    team_id=handle.runtime.team_id,
                )
                response_payload = {"error": str(err)}

        response_json = json.dumps(response_payload, ensure_ascii=False, default=str)
        response_bytes = response_json.encode("utf-8")
        response_blob = f"{len(response_bytes)}\n".encode() + response_bytes

        sandbox_class = self._get_sandbox_class(handle.backend)
        sandbox = sandbox_class.get_by_id(handle.sandbox_id)
        result = sandbox.write_file(response_path, response_blob)
        if result.exit_code != 0:
            logger.warning(
                "notebook_bridge_response_write_failed",
                stdout=result.stdout,
                stderr=result.stderr,
                sandbox_id=handle.sandbox_id,
            )

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

    def _normalize_user_expression_string(self, value: str | None) -> str | None:
        if not value:
            return None
        stripped = value.strip()
        if stripped in {"None", "null"}:
            return None
        if len(stripped) >= 2 and (
            (stripped.startswith("'") and stripped.endswith("'"))
            or (stripped.startswith('"') and stripped.endswith('"'))
        ):
            stripped = stripped[1:-1]
        return stripped or None

    def _build_user_expressions(self, variable_names: list[str]) -> dict[str, str] | None:
        if not variable_names:
            return None
        expressions: dict[str, str] = {}
        for name in variable_names:
            expressions[f"{self._TYPE_EXPRESSION_PREFIX}{name}"] = f"type({name}).__name__"
            expressions[f"{self._HOGQL_QUERY_EXPRESSION_PREFIX}{name}"] = (
                f"{name}._query if type({name}).__name__ == 'HogQLLazyFrame' else None"
            )
        return expressions

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
            self._bootstrap_kernel(sandbox, connection_file, notebook, user)
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

    def _bootstrap_kernel(
        self, sandbox: SandboxProtocol, connection_file: str, notebook: Notebook, user: User | None
    ) -> None:
        code = self._build_kernel_bootstrap_code(notebook, user, sandbox.id)
        if not code:
            return
        payload = {
            "connection_file": connection_file,
            "timeout": int(self._startup_timeout),
            "code": code,
            "user_expressions": None,
        }
        command = self._build_kernel_command(payload, action="execute")
        result = sandbox.execute(command, timeout_seconds=int(self._startup_timeout))
        if result.exit_code != 0:
            logger.warning(
                "notebook_kernel_bootstrap_failed",
                stdout=result.stdout,
                stderr=result.stderr,
                notebook_short_id=notebook.short_id,
            )
            return
        lines = result.stdout.strip().splitlines()
        if not lines:
            logger.warning("notebook_kernel_bootstrap_missing_output", notebook_short_id=notebook.short_id)
            return
        try:
            payload_out = json.loads(lines[-1])
        except json.JSONDecodeError:
            logger.warning(
                "notebook_kernel_bootstrap_unparseable",
                stdout=result.stdout,
                notebook_short_id=notebook.short_id,
            )
            return
        if payload_out.get("status") not in ("ok", None):
            logger.warning(
                "notebook_kernel_bootstrap_error",
                status=payload_out.get("status"),
                stderr=payload_out.get("stderr"),
                traceback=payload_out.get("traceback"),
                notebook_short_id=notebook.short_id,
            )

    def _build_kernel_bootstrap_code(self, notebook: Notebook, user: User | None, sandbox_id: str | None) -> str:
        return (
            "import duckdb\n"
            "import json\n"
            "import os\n"
            "import re\n"
            "import tempfile\n"
            "import time\n"
            "from typing import Any, Sequence\n"
            "\n"
            "_duckdb_connection = duckdb.connect(database=':memory:')\n"
            "\n"
            "def duck_execute(sql: str, parameters: Sequence[Any] | dict[str, Any] | None = None):\n"
            "    if parameters is None:\n"
            "        return _duckdb_connection.execute(sql).df()\n"
            "    return _duckdb_connection.execute(sql, parameters).df()\n"
            "\n"
            "def duck_save_table(name: str, data: Any) -> None:\n"
            "    if not name or not name.replace('_', '').isalnum():\n"
            "        raise ValueError('Invalid table name')\n"
            '    temp_name = f"__notebook_{name}"\n'
            "    table_identifier = f'\"{name}\"'\n"
            "    temp_identifier = f'\"{temp_name}\"'\n"
            "    _duckdb_connection.register(temp_name, data)\n"
            "    _duckdb_connection.execute(\n"
            '        f"CREATE OR REPLACE TABLE {table_identifier} AS SELECT * FROM {temp_identifier}"\n'
            "    )\n"
            "    _duckdb_connection.unregister(temp_name)\n"
            "\n"
            "def notebook_dataframe_page(value: Any, *, offset: int = 0, limit: int = 10) -> dict[str, Any] | None:\n"
            "    try:\n"
            "        import pandas as pd\n"
            "    except Exception:\n"
            "        return None\n"
            "    if value is None:\n"
            "        return None\n"
            "    if hasattr(value, 'to_df'):\n"
            "        value = value.to_df()\n"
            "    elif hasattr(value, 'to_pandas'):\n"
            "        value = value.to_pandas()\n"
            "    if not isinstance(value, pd.DataFrame):\n"
            "        return None\n"
            "    total_rows = len(value)\n"
            "    offset = max(0, min(offset, total_rows))\n"
            "    limit = max(1, limit)\n"
            "    page = value.iloc[offset : offset + limit]\n"
            "    rows = json.loads(page.to_json(orient='records', date_format='iso'))\n"
            "    return {\n"
            "        'columns': [str(col) for col in page.columns.tolist()],\n"
            "        'rows': rows,\n"
            "        'row_count': total_rows,\n"
            "    }\n"
            "\n"
            f"_NOTEBOOK_BRIDGE_PREFIX = '__NOTEBOOK_BRIDGE_{sandbox_id or 'unknown'}__'\n"
            "\n"
            "def _notebook_bridge_write(payload: dict[str, Any]) -> None:\n"
            "    payload_bytes = json.dumps(payload, ensure_ascii=True).encode('utf-8')\n"
            "    header = f\"{_NOTEBOOK_BRIDGE_PREFIX}{len(payload_bytes)} \".encode('utf-8')\n"
            '    data = header + payload_bytes + b"\\n"\n'
            "    offset = 0\n"
            "    while offset < len(data):\n"
            "        written = os.write(1, data[offset:])\n"
            "        if written <= 0:\n"
            "            raise RuntimeError('Failed to write HogQL request')\n"
            "        offset += written\n"
            "\n"
            '_HOGQL_PLACEHOLDER_PATTERN = re.compile(r"\\{([A-Za-z_][\\w$]*)\\}")\n'
            "\n"
            "def _find_hogql_placeholders(query: str) -> list[str]:\n"
            "    if not query:\n"
            "        return []\n"
            "\n"
            "    # Strip SQL comments before finding placeholders\n"
            "    # First, remove multi-line comments\n"
            '    while "/*" in query and "*/" in query:\n'
            '        start = query.find("/*")\n'
            '        end = query.find("*/", start) + 2\n'
            "        query = query[:start] + ' ' + query[end:]\n"
            "\n"
            "    # Then remove single-line comments\n"
            "    lines = query.split('\\n')\n"
            "    cleaned_lines = []\n"
            "    for line in lines:\n"
            "        cleaned_lines.append(line.split('--')[0])\n"
            "    query = '\\n'.join(cleaned_lines)\n"
            "\n"
            "    # Find placeholders in the cleaned query\n"
            "    seen = set()\n"
            "    names = []\n"
            "    for match in _HOGQL_PLACEHOLDER_PATTERN.finditer(query):\n"
            "        name = match.group(1)\n"
            "        if name and name not in seen:\n"
            "            seen.add(name)\n"
            "            names.append(name)\n"
            "    return names\n"
            "\n"
            "def _hogql_execute_raw(\n"
            "    query: str, *, timeout: float | None = 30.0, placeholders: dict[str, Any] | None = None\n"
            ") -> Any:\n"
            "    if not isinstance(query, str):\n"
            "        raise ValueError('query must be a string')\n"
            "    fd, response_path = tempfile.mkstemp(prefix='hogql_response_', suffix='.json')\n"
            "    os.close(fd)\n"
            "    os.unlink(response_path)\n"
            "    payload = {'call': 'hogql_execute', 'query': query, 'response_path': response_path}\n"
            "    if placeholders:\n"
            "        payload['placeholders'] = placeholders\n"
            "    _notebook_bridge_write(payload)\n"
            "    start_time = time.monotonic()\n"
            "    while not os.path.exists(response_path):\n"
            "        if timeout is not None and time.monotonic() - start_time > timeout:\n"
            "            raise TimeoutError('Timed out waiting for HogQL response')\n"
            "        time.sleep(0.1)\n"
            "    expected_length: int | None = None\n"
            "    data = b''\n"
            "    with open(response_path, 'rb') as response_file:\n"
            "        header = response_file.readline()\n"
            "        if not header:\n"
            "            raise RuntimeError('Empty HogQL response')\n"
            "        try:\n"
            "            expected_length = int(header.strip() or b'0')\n"
            "        except ValueError:\n"
            "            raise RuntimeError('Invalid HogQL response length')\n"
            "        while expected_length is not None and len(data) < expected_length:\n"
            "            chunk = response_file.read(expected_length - len(data))\n"
            "            if chunk:\n"
            "                data += chunk\n"
            "                continue\n"
            "            if timeout is not None and time.monotonic() - start_time > timeout:\n"
            "                raise TimeoutError('Timed out reading HogQL response')\n"
            "            time.sleep(0.1)\n"
            "    try:\n"
            "        os.unlink(response_path)\n"
            "    except Exception:\n"
            "        pass\n"
            "    if expected_length is None or len(data) != expected_length:\n"
            "        raise RuntimeError('Incomplete HogQL response')\n"
            "    text = data.decode('utf-8')\n"
            "    try:\n"
            "        return json.loads(text)\n"
            "    except Exception:\n"
            "        return text\n"
            "\n"
            "class HogQLLazyFrame:\n"
            "    def __init__(\n"
            "        self, query: str, *, timeout: float | None = 30.0, placeholders: list[str] | None = None\n"
            "    ) -> None:\n"
            "        if not isinstance(query, str):\n"
            "            raise ValueError('query must be a string')\n"
            "        self._query = query\n"
            "        self._timeout = timeout\n"
            "        self._placeholders = placeholders or []\n"
            "        self._response: dict[str, Any] | str | None = None\n"
            "        self._dataframe: Any | None = None\n"
            "\n"
            "    def _get_response(self) -> dict[str, Any] | str:\n"
            "        if self._response is None:\n"
            "            placeholders = _resolve_hogql_placeholders(self._placeholders) if self._placeholders else None\n"
            "            self._response = _hogql_execute_raw(self._query, timeout=self._timeout, placeholders=placeholders)\n"
            "        return self._response\n"
            "\n"
            "    def to_json(self) -> dict[str, Any] | str:\n"
            "        return self._get_response()\n"
            "\n"
            "    def to_df(self) -> Any:\n"
            "        if self._dataframe is None:\n"
            "            import pandas as pd\n"
            "\n"
            "            response = self._get_response()\n"
            "            if isinstance(response, dict) and response.get('error'):\n"
            "                raise RuntimeError(response['error'])\n"
            "            if not isinstance(response, dict):\n"
            "                raise RuntimeError('Unexpected HogQL response type')\n"
            "            results = response.get('results') or []\n"
            "            columns = response.get('columns') or []\n"
            "            self._dataframe = pd.DataFrame(results, columns=columns)\n"
            "        return self._dataframe\n"
            "\n"
            "    def to_pandas(self) -> Any:\n"
            "        return self.to_df()\n"
            "\n"
            "    def __dataframe__(self, *args: Any, **kwargs: Any) -> Any:\n"
            "        return self.to_df().__dataframe__(*args, **kwargs)\n"
            "\n"
            "    def __getattr__(self, name: str) -> Any:\n"
            "        return getattr(self.to_df(), name)\n"
            "\n"
            "    def __getitem__(self, item: Any) -> Any:\n"
            "        return self.to_df().__getitem__(item)\n"
            "\n"
            "    def __setitem__(self, key: Any, value: Any) -> None:\n"
            "        self.to_df().__setitem__(key, value)\n"
            "\n"
            "    def __repr__(self) -> str:\n"
            '        return f"HogQLLazyFrame(query={self._query!r})"\n'
            "\n"
            "    def __str__(self) -> str:\n"
            "        return str(self.to_df())\n"
            "\n"
            "    def _repr_html_(self) -> str:\n"
            "        return self.to_df()._repr_html_()\n"
            "\n"
            "    def _repr_markdown_(self) -> str:\n"
            "        return self.to_df()._repr_markdown_()\n"
            "\n"
            "    def _repr_pretty_(self, printer: Any, cycle: bool) -> None:\n"
            "        return self.to_df()._repr_pretty_(printer, cycle)\n"
            "\n"
            "    def _repr_mimebundle_(self, include: Any = None, exclude: Any = None) -> dict[str, Any]:\n"
            "        return self.to_df()._repr_mimebundle_(include=include, exclude=exclude)\n"
            "\n"
            "    def _ipython_display_(self) -> None:\n"
            "        return self.to_df()._ipython_display_()\n"
            "\n"
            "def _serialize_hogql_placeholder(value: Any) -> dict[str, Any]:\n"
            "    if isinstance(value, HogQLLazyFrame):\n"
            "        return {'type': 'hogql_query', 'query': value._query}\n"
            "    if isinstance(value, (str, int, float, bool)) or value is None:\n"
            "        return {'type': 'constant', 'value': value}\n"
            "    if isinstance(value, (list, tuple)):\n"
            "        return {'type': 'constant', 'value': list(value)}\n"
            "    if isinstance(value, dict):\n"
            "        return {'type': 'constant', 'value': value}\n"
            "    raise ValueError(f'Unsupported HogQL placeholder type: {type(value).__name__}')\n"
            "\n"
            "def _resolve_hogql_placeholders(names: list[str]) -> dict[str, Any]:\n"
            "    placeholders: dict[str, Any] = {}\n"
            "    for name in names:\n"
            "        if name not in globals():\n"
            "            raise KeyError(f\"HogQL placeholder '{name}' is not defined.\")\n"
            "        placeholders[name] = _serialize_hogql_placeholder(globals()[name])\n"
            "    return placeholders\n"
            "\n"
            "def hogql_execute(\n"
            "    query: str, *, timeout: float | None = 30.0, placeholders: Sequence[str] | None = None\n"
            ") -> HogQLLazyFrame:\n"
            "    placeholder_list = _find_hogql_placeholders(query) if placeholders is None else list(placeholders)\n"
            "    return HogQLLazyFrame(query, timeout=timeout, placeholders=placeholder_list)\n"
        )

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
            "python3 -u - <<'EOF_KERNEL_CMD_EXEC'\n"
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
            "stream = bool(payload.get('stream', False))\n"
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
            "        media = []\n"
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
            "                text = content.get('text', '')\n"
            "                destination.append(text)\n"
            "                if stream:\n"
            "                    print(json.dumps({'type': 'stream', 'name': content.get('name'), 'text': text}), "
            "flush=True)\n"
            "                continue\n"
            "            if msg_type in ('execute_result', 'display_data'):\n"
            "                data = content.get('data') or {}\n"
            "                result = data or result\n"
            "                execution_count = content.get('execution_count', execution_count)\n"
            "                for mime_type in ('image/png', 'image/jpeg', 'image/svg+xml'):\n"
            "                    image_data = data.get(mime_type)\n"
            "                    if isinstance(image_data, str):\n"
            "                        media.append({'mime_type': mime_type, 'data': image_data})\n"
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
            "            'media': media,\n"
            "            'execution_count': execution_count,\n"
            "            'error_name': error_name,\n"
            "            'traceback': traceback_lines,\n"
            "            'user_expressions': user_expressions_result,\n"
            "        }\n"
            "        if stream:\n"
            "            payload_out['type'] = 'result'\n"
            "        print(json.dumps(payload_out))\n"
            "except Empty:\n"
            "    payload_out = {'status': 'timeout', 'stdout': '', 'stderr': '', 'result': None, "
            "'media': [], 'execution_count': None, 'error_name': None, 'traceback': [], 'user_expressions': None}\n"
            "    if stream:\n"
            "        payload_out['type'] = 'result'\n"
            "    print(json.dumps(payload_out))\n"
            "except Exception as err:\n"
            "    payload_out = {\n"
            "        'status': 'error',\n"
            "        'stdout': '',\n"
            "        'stderr': str(err),\n"
            "        'result': None,\n"
            "        'media': [],\n"
            "        'execution_count': None,\n"
            "        'error_name': err.__class__.__name__,\n"
            "        'traceback': traceback.format_exception(type(err), err, err.__traceback__),\n"
            "        'user_expressions': None,\n"
            "    }\n"
            "    if stream:\n"
            "        payload_out['type'] = 'result'\n"
            "    print(json.dumps(payload_out))\n"
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
        user_expressions = self._build_user_expressions(variable_names) if capture_variables else None

        payload = {
            "connection_file": handle.runtime.connection_file,
            "timeout": timeout_seconds,
            "code": code,
            "user_expressions": user_expressions,
            "stream": True,
        }
        command = self._build_kernel_command(payload, action="execute")
        sandbox_class = self._get_sandbox_class(handle.backend)
        sandbox = sandbox_class.get_by_id(handle.sandbox_id)
        started_at = timezone.now()
        stream = sandbox.execute_stream(command, timeout_seconds=timeout_seconds)

        payload_out: dict[str, Any] | None = None
        marker = self._notebook_bridge_marker(handle)
        bridge_parser = _NotebookBridgeParser(marker=marker)

        for line in stream.iter_stdout():
            event = self._parse_kernel_stream_line(line, handle=handle, bridge_parser=bridge_parser)
            if event and event["type"] == "result":
                payload_out = event["data"]

        result = stream.wait()
        if result.exit_code != 0:
            raise RuntimeError(f"Kernel execution failed: {result.stdout} {result.stderr}")

        if payload_out is None:
            output_lines = [line for line in result.stdout.splitlines() if line.strip()]
            if output_lines:
                try:
                    payload_out = json.loads(output_lines[-1])
                except json.JSONDecodeError as err:
                    raise RuntimeError("Kernel execution returned no output.") from err
            else:
                raise RuntimeError("Kernel execution returned no output.")

        payload_out["stdout"] = self._strip_notebook_bridge_messages(payload_out.get("stdout", ""), marker)

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
            media=payload_out.get("media", []) or [],
            execution_count=execution_count,
            error_name=error_name,
            traceback=traceback,
            variables=variables,
            started_at=started_at,
            completed_at=timezone.now(),
            kernel_runtime=handle.runtime,
        )

    def _execute_in_sandbox_stream(
        self,
        handle: _KernelHandle,
        code: str,
        *,
        capture_variables: bool,
        variable_names: list[str],
        timeout: float | None,
    ):
        if not handle.sandbox_id:
            raise RuntimeError("Sandbox not available for kernel execution.")

        timeout_seconds = int(timeout or self._execution_timeout)
        user_expressions = self._build_user_expressions(variable_names) if capture_variables else None

        payload = {
            "connection_file": handle.runtime.connection_file,
            "timeout": timeout_seconds,
            "code": code,
            "user_expressions": user_expressions,
            "stream": True,
        }
        command = self._build_kernel_command(payload, action="execute")
        sandbox_class = self._get_sandbox_class(handle.backend)
        sandbox = sandbox_class.get_by_id(handle.sandbox_id)
        started_at = timezone.now()
        stream = sandbox.execute_stream(command, timeout_seconds=timeout_seconds)

        payload_out: dict[str, Any] | None = None
        marker = self._notebook_bridge_marker(handle)
        bridge_parser = _NotebookBridgeParser(marker=marker)

        for line in stream.iter_stdout():
            event = self._parse_kernel_stream_line(line, handle=handle, bridge_parser=bridge_parser)
            if not event:
                continue
            if event["type"] == "result":
                payload_out = event["data"]
                continue
            if event["text"]:
                yield event

        remaining_text = bridge_parser.flush()
        if remaining_text:
            yield {"type": "stdout", "text": remaining_text}

        result = stream.wait()
        if result.exit_code != 0:
            raise RuntimeError(f"Kernel execution failed: {result.stdout} {result.stderr}")

        if payload_out is None:
            output_lines = [line for line in result.stdout.splitlines() if line.strip()]
            if output_lines:
                try:
                    payload_out = json.loads(output_lines[-1])
                except json.JSONDecodeError as err:
                    raise RuntimeError("Kernel execution returned no output.") from err
            else:
                raise RuntimeError("Kernel execution returned no output.")

        payload_out["stdout"] = self._strip_notebook_bridge_messages(payload_out.get("stdout", ""), marker)
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

        execution_result = KernelExecutionResult(
            status=status,
            stdout=payload_out.get("stdout", ""),
            stderr=payload_out.get("stderr", ""),
            result=payload_out.get("result"),
            media=payload_out.get("media", []) or [],
            execution_count=execution_count,
            error_name=error_name,
            traceback=traceback,
            variables=variables,
            started_at=started_at,
            completed_at=timezone.now(),
            kernel_runtime=handle.runtime,
        )

        yield {"type": "result", "data": execution_result.as_dict()}

    def _parse_kernel_stream_line(
        self,
        line: str,
        *,
        handle: _KernelHandle,
        bridge_parser: _NotebookBridgeParser,
    ) -> dict[str, Any] | None:
        trimmed = line.strip()
        if not trimmed:
            return None
        try:
            chunk = json.loads(trimmed)
        except json.JSONDecodeError:
            return None
        if chunk.get("type") == "stream":
            stream_name = chunk.get("name")
            text = chunk.get("text", "")
            if stream_name == "stdout":
                filtered_text, payloads = bridge_parser.feed(text)
                for payload_json in payloads:
                    self._handle_notebook_bridge_payload(payload_json, handle)
                return {"type": "stdout", "text": filtered_text}
            if stream_name == "stderr":
                return {"type": "stderr", "text": text}
            return None
        if chunk.get("type") == "result":
            return {"type": "result", "data": chunk}
        return None

    def dataframe_page(
        self,
        notebook: Notebook,
        user: User | None,
        variable_name: str,
        *,
        offset: int = 0,
        limit: int = 10,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if not variable_name.isidentifier():
            raise ValueError("Variable name must be a valid identifier.")

        code = (
            "import json\n"
            f"_notebook_dataframe_result = notebook_dataframe_page({variable_name}, offset={offset}, limit={limit})\n"
            "print(json.dumps(_notebook_dataframe_result))\n"
        )
        execution = self.execute(
            notebook,
            user,
            code,
            capture_variables=False,
            variable_names=[],
            timeout=timeout,
        )
        if execution.status != "ok":
            raise RuntimeError(execution.stderr or "Failed to fetch dataframe data.")

        output_lines = [line for line in execution.stdout.splitlines() if line.strip()]
        if not output_lines:
            raise RuntimeError("No dataframe output returned.")
        try:
            payload = json.loads(output_lines[-1])
        except json.JSONDecodeError as err:
            raise RuntimeError("Failed to parse dataframe output.") from err
        if payload is None:
            raise ValueError("Variable is not a dataframe.")
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected dataframe response.")
        return payload


notebook_kernel_runtime_service = KernelRuntimeService()


def get_kernel_runtime(notebook: Notebook, user: User | None) -> KernelRuntimeSession:
    return notebook_kernel_runtime_service.get_kernel_runtime(notebook, user)
