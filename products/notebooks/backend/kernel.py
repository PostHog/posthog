from __future__ import annotations

import ast
import json
import uuid
import atexit
import signal
import threading
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from queue import Empty
from typing import Any, Literal

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

import structlog
from jupyter_client import KernelManager
from jupyter_client.blocking import BlockingKernelClient

from posthog.models import User

from products.notebooks.backend.models import Notebook

logger = structlog.get_logger(__name__)

HOGQL_BOOTSTRAP_CODE = """
import json
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType

from posthog.hogql.parser import parse_expr as _posthog_parse_expr, parse_select as _posthog_parse_select
import posthog.hogql.ast as _posthog_hogql_ast

logging.getLogger().setLevel(logging.ERROR)
logging.getLogger("posthog").setLevel(logging.ERROR)
logging.getLogger("django").setLevel(logging.ERROR)

__posthog_team_id = None
__posthog_user_id = None
_posthog_django_ready = False


def _posthog_is_jsonable(value):
    try:
        json.dumps(value)
        return True
    except Exception:
        return False


def _posthog_is_exportable(value):
    return not callable(value) and not isinstance(value, ModuleType)


def _posthog_variable_snapshot(value):
    kind = "hogql_ast" if isinstance(value, _posthog_hogql_ast.AST) else ("json" if _posthog_is_jsonable(value) else "scalar")
    repr_value = repr(value)
    if kind == "hogql_ast":
        try:
            repr_value = value.to_hogql() if hasattr(value, "to_hogql") else str(value)
            if not repr_value.startswith("sql("):
                repr_value = f"sql({repr_value})"
        except Exception:
            # If printing fails (e.g. Django app registry not ready), fall back to a safe repr
            repr_value = repr(value)
    return {
        "repr": repr_value,
        "type": type(value).__name__,
        "module": getattr(type(value), "__module__", None),
        "kind": kind,
    }


globals()["parse_expr"] = _posthog_parse_expr
globals()["parse_select"] = _posthog_parse_select
globals()["hogql_ast"] = _posthog_hogql_ast
for _name, _value in vars(_posthog_hogql_ast).items():
    if isinstance(_value, type) and getattr(_value, "__module__", "").startswith(_posthog_hogql_ast.__name__):
        globals()[_name] = _value


def _posthog_setup_django():
    global _posthog_django_ready
    if _posthog_django_ready:
        return

    import django

    django.setup()
    _posthog_django_ready = True


def _posthog_hogql_query_from_input(raw):
    from posthog.schema import HogQLASTQuery as _posthog_HogQLASTQuery, HogQLQuery as _posthog_HogQLQuery

    if isinstance(raw, _posthog_hogql_ast.AST):
        return _posthog_HogQLQuery(query=raw.to_hogql())

    if isinstance(raw, str):
        return _posthog_HogQLQuery(query=raw)

    if isinstance(raw, dict):
        kind = raw.get("kind")
        if kind == "HogQLQuery":
            return _posthog_HogQLQuery.model_validate(raw)
        if kind == "HogQLASTQuery":
            return _posthog_HogQLASTQuery.model_validate(raw)

    raise ValueError("Unsupported query format. Provide a HogQL string, AST node, or query dict with a kind.")


def _posthog_run_sync(query):
    from posthog.api.services.query import process_query_model as _posthog_process_query_model
    from posthog.hogql_queries.query_runner import ExecutionMode as _posthog_ExecutionMode
    from posthog.models import Team as _posthog_Team, User as _posthog_User

    if __posthog_team_id is None:
        raise ValueError("No team configured for PostHog notebook run.")

    team = _posthog_Team.objects.get(id=__posthog_team_id)
    user = _posthog_User.objects.get(id=__posthog_user_id) if __posthog_user_id is not None else None
    hogql_query = _posthog_hogql_query_from_input(query)

    result = _posthog_process_query_model(
        team,
        hogql_query,
        execution_mode=_posthog_ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        user=user,
    )

    return result.model_dump(by_alias=True) if hasattr(result, "model_dump") else result


def _posthog_run_in_thread(query):
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_posthog_run_sync, query)
        return future.result()


def run(query):
    _posthog_setup_django()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _posthog_run_sync(query)

    return _posthog_run_in_thread(query)
"""

VARIABLE_CAPTURE_EXPRESSION = "{k: _posthog_variable_snapshot(v) for k, v in locals().items() if not k.startswith('_') and _posthog_is_exportable(v) and k not in {'In', 'Out'}}"


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
    variables: list[KernelVariable]
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
            "variables": [variable.as_dict() for variable in self.variables],
            "execution_count": self.execution_count,
            "error_name": self.error_name,
            "traceback": self.traceback,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "kernel": self.kernel.as_dict(),
        }


@dataclass
class KernelVariable:
    name: str
    repr: str
    type: str
    module: str | None
    kind: Literal["hogql_ast", "json", "scalar"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "repr": self.repr,
            "type": self.type,
            "module": self.module,
            "kind": self.kind,
        }


@dataclass
class _KernelHandle:
    id: str
    notebook_short_id: str
    team_id: int
    manager: KernelManager
    client: BlockingKernelClient
    lock: threading.RLock
    started_at: datetime
    last_activity_at: datetime
    execution_count: int = 0
    initialized: bool = False
    context_user_id: int | None = None
    context_applied: bool = False

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
        user: User | None = None,
    ) -> KernelExecutionResult:
        handle = self._ensure_handle(notebook)

        with handle.lock:
            if not handle.manager.is_alive():
                handle = self._reset_handle(notebook, handle)

            timeout_seconds = timeout or self._execution_timeout
            started_at = timezone.now()
            self._set_context_variables(handle, user)
            stdout: list[str] = []
            stderr: list[str] = []
            traceback: list[str] = []
            result: dict[str, Any] | None = None
            variables: list[KernelVariable] = []
            status = "ok"
            execution_count: int | None = None
            error_name: str | None = None

            expression_key = "__posthog_variables__"
            msg_id = handle.client.execute(
                code,
                stop_on_error=False,
                user_expressions={expression_key: VARIABLE_CAPTURE_EXPRESSION} if capture_variables else None,
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

    def store_value(self, notebook: Notebook, variable_name: str, value: Any) -> bool:
        serialized_value = self._serialize_value_for_kernel(value)
        if not variable_name or serialized_value is None:
            return False

        assignment_code = "\n".join(
            [
                "import json",
                f"{variable_name} = json.loads({json.dumps(serialized_value)})",
            ]
        )

        try:
            execution = self.execute(
                notebook,
                assignment_code,
                capture_variables=False,
            )
        except RuntimeError:
            logger.exception("notebook_kernel_store_value_failed", notebook_short_id=notebook.short_id)
            return False

        return execution.status == "ok"

    def _serialize_value_for_kernel(self, value: Any) -> str | None:
        try:
            return json.dumps(value, cls=DjangoJSONEncoder)
        except TypeError:
            try:
                return json.dumps(value, default=str)
            except Exception:
                logger.warning("notebook_kernel_variable_serialization_failed")
                return None

    def _parse_variables(self, user_expressions: dict[str, Any], expression_key: str) -> list[KernelVariable]:
        expression = user_expressions.get(expression_key)
        if not expression or expression.get("status") != "ok":
            return []

        data = expression.get("data", {})
        text_value = data.get("text/plain")
        if not isinstance(text_value, str):
            return []

        try:
            parsed = ast.literal_eval(text_value)
        except Exception:
            logger.warning("notebook_kernel_variables_parse_failed")
            return []

        if not isinstance(parsed, dict):
            return []

        variables: list[KernelVariable] = []
        for name, raw in parsed.items():
            if not isinstance(raw, dict):
                continue

            kind = raw.get("kind") if raw.get("kind") in {"hogql_ast", "json", "scalar"} else "scalar"

            variables.append(
                KernelVariable(
                    name=str(name),
                    repr=str(raw.get("repr", "")),
                    type=str(raw.get("type", "")),
                    module=str(raw.get("module")) if raw.get("module") is not None else None,
                    kind=kind,
                )
            )

        return sorted(variables, key=lambda variable: variable.name)

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
                    team_id=notebook.team_id,
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

            setup_success = self._run_setup_code(handle, HOGQL_BOOTSTRAP_CODE)
            context_success = self._set_context_variables(handle, None) if setup_success else False
            handle.initialized = setup_success and context_success
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

    def _set_context_variables(self, handle: _KernelHandle, user: User | None) -> bool:
        user_id = user.id if isinstance(user, User) else None
        if handle.context_applied and handle.context_user_id == user_id:
            return True

        context_code = "\n".join(
            [
                f"__posthog_team_id = {handle.team_id}",
                f"__posthog_user_id = {user_id if user_id is not None else 'None'}",
            ]
        )
        success = self._run_setup_code(handle, context_code)
        if not success:
            logger.warning("notebook_kernel_context_failed", kernel_id=handle.id)
            return False

        handle.context_user_id = user_id
        handle.context_applied = True
        return True

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
