from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from products.notebooks.backend.kernel_runtime import KernelRuntimeService, _KernelHandle, build_notebook_sandbox_config
from products.notebooks.backend.models import KernelRuntime, Notebook


class _DummyLock:
    def __enter__(self) -> _DummyLock:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        return None


@dataclass
class _FakeExecutionResult:
    stdout: str
    stderr: str = ""
    exit_code: int = 0


class _FakeSandbox:
    def __init__(self, result: _FakeExecutionResult) -> None:
        self.result = result
        self.command: str | None = None
        self.timeout_seconds: int | None = None

    def execute(self, command: str, timeout_seconds: int | None = None) -> _FakeExecutionResult:
        self.command = command
        self.timeout_seconds = timeout_seconds
        return self.result


class _FakeSandboxClass:
    sandbox: _FakeSandbox

    @staticmethod
    def get_by_id(sandbox_id: str) -> _FakeSandbox:
        return _FakeSandboxClass.sandbox


class TestKernelRuntimeService(BaseTest):
    @parameterized.expand(
        [
            (
                "cpu_memory_timeout",
                {
                    "kernel_cpu_cores": 2.5,
                    "kernel_memory_gb": 8.0,
                    "kernel_idle_timeout_seconds": 120,
                },
                {
                    "cpu_cores": 2.5,
                    "memory_gb": 8.0,
                    "ttl_seconds": 120,
                },
            ),
            (
                "memory_only",
                {"kernel_memory_gb": 12.0},
                {"memory_gb": 12.0},
            ),
        ]
    )
    def test_build_notebook_sandbox_config(
        self, _name: str, notebook_kwargs: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        notebook = Notebook.objects.create(team=self.team, **notebook_kwargs)

        sandbox_config = build_notebook_sandbox_config(notebook)

        assert sandbox_config.template.value == "notebook_base"
        assert sandbox_config.name == f"notebook-kernel-{notebook.short_id}"
        for key, value in expected.items():
            assert getattr(sandbox_config, key) == value

    @parameterized.expand(
        [
            (
                "non_dict_returns_none",
                "not-a-dict",
                None,
            ),
            (
                "empty_dict_returns_none",
                {},
                None,
            ),
            (
                "ok_with_type",
                {
                    "answer": {"status": "ok"},
                    "__type__answer": {"status": "ok", "data": {"text/plain": "'int'"}},
                },
                {"answer": {"status": "ok", "type": "int"}},
            ),
            (
                "error_payload",
                {
                    "oops": {
                        "status": "error",
                        "ename": "NameError",
                        "evalue": "missing",
                        "traceback": ["traceback"],
                    }
                },
                {
                    "oops": {
                        "status": "error",
                        "ename": "NameError",
                        "evalue": "missing",
                        "traceback": ["traceback"],
                    }
                },
            ),
        ]
    )
    def test_parse_user_expressions(self, _name: str, payload: Any, expected: dict[str, Any] | None) -> None:
        service = KernelRuntimeService()

        assert service._parse_user_expressions(payload) == expected

    @override_settings(SANDBOX_PROVIDER=KernelRuntime.Backend.MODAL, DEBUG=False, TEST=False)
    def test_get_backend_requires_modal_credentials(self) -> None:
        service = KernelRuntimeService()

        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesMessage(RuntimeError, "Modal credentials are required to start notebook kernels"):
                service._get_backend(require_credentials=True)

    def test_execute_filters_invalid_variable_names(self) -> None:
        service = KernelRuntimeService()
        notebook = Notebook.objects.create(team=self.team)
        runtime = KernelRuntime.objects.create(
            team=self.team,
            notebook=notebook,
            notebook_short_id=notebook.short_id,
            user=self.user,
            status=KernelRuntime.Status.RUNNING,
            backend=KernelRuntime.Backend.DOCKER,
            connection_file="/tmp/connection.json",
            sandbox_id="sandbox-1",
        )
        handle = _KernelHandle(
            runtime=runtime,
            lock_name="lock",
            started_at=timezone.now(),
            last_activity_at=timezone.now(),
            backend=KernelRuntime.Backend.DOCKER,
            sandbox_id=runtime.sandbox_id,
        )

        with (
            patch.object(service, "_ensure_handle", return_value=handle),
            patch.object(service, "_acquire_lock", return_value=_DummyLock()),
            patch.object(service, "_is_handle_alive", return_value=True),
            patch.object(service, "_execute_in_sandbox", return_value="ok") as mocked_execute,
        ):
            result = service.execute(
                notebook,
                self.user,
                "code",
                capture_variables=True,
                variable_names=["valid", "not valid", "123", "_also_valid"],
            )

        assert result == "ok"  # type: ignore
        assert mocked_execute.call_args.kwargs["variable_names"] == ["valid", "_also_valid"]

    def test_execute_in_sandbox_parses_output(self) -> None:
        service = KernelRuntimeService(execution_timeout=5)
        notebook = Notebook.objects.create(team=self.team)
        runtime = KernelRuntime.objects.create(
            team=self.team,
            notebook=notebook,
            notebook_short_id=notebook.short_id,
            user=self.user,
            status=KernelRuntime.Status.RUNNING,
            backend=KernelRuntime.Backend.DOCKER,
            connection_file="/tmp/connection.json",
            sandbox_id="sandbox-1",
        )
        handle = _KernelHandle(
            runtime=runtime,
            lock_name="lock",
            started_at=timezone.now(),
            last_activity_at=timezone.now(),
            backend=KernelRuntime.Backend.DOCKER,
            sandbox_id=runtime.sandbox_id,
        )
        payload_out = {
            "status": "ok",
            "stdout": "hello",
            "stderr": "",
            "result": {"text/plain": "42"},
            "execution_count": 3,
            "error_name": None,
            "traceback": [],
            "user_expressions": {
                "answer": {"status": "ok"},
                "__type__answer": {"status": "ok", "data": {"text/plain": "'int'"}},
            },
        }
        result = _FakeExecutionResult(stdout=f"log\n{json.dumps(payload_out)}")
        sandbox = _FakeSandbox(result)
        _FakeSandboxClass.sandbox = sandbox

        with patch.object(service, "_get_sandbox_class", return_value=_FakeSandboxClass):
            execution_result = service._execute_in_sandbox(
                handle,
                "print('hi')",
                capture_variables=True,
                variable_names=["answer"],
                timeout=5,
            )

        assert execution_result.status == "ok"
        assert execution_result.stdout == "hello"
        assert execution_result.execution_count == 3
        assert execution_result.variables == {"answer": {"status": "ok", "type": "int"}}
        assert handle.execution_count == 3
        assert sandbox.timeout_seconds == 5
