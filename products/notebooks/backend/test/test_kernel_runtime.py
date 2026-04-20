from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from products.notebooks.backend.kernel_runtime import (
    KernelRuntimeService,
    _KernelHandle,
    _NotebookBridgeParser,
    build_notebook_sandbox_config,
)
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
    def __init__(self, result: _FakeExecutionResult, stream: _FakeSandboxStream | None = None) -> None:
        self.result = result
        self.stream = stream
        self.command: str | None = None
        self.timeout_seconds: int | None = None

    def execute(self, command: str, timeout_seconds: int | None = None) -> _FakeExecutionResult:
        self.command = command
        self.timeout_seconds = timeout_seconds
        return self.result

    def execute_stream(self, command: str, timeout_seconds: int | None = None) -> _FakeSandboxStream:
        self.command = command
        self.timeout_seconds = timeout_seconds
        if self.stream is None:
            raise RuntimeError("Fake sandbox stream not configured")
        return self.stream


class _FakeSandboxStream:
    def __init__(self, stdout_lines: list[str], result: _FakeExecutionResult) -> None:
        self._stdout_lines = stdout_lines
        self._result = result

    def iter_stdout(self):
        yield from self._stdout_lines

    def wait(self) -> _FakeExecutionResult:
        return self._result


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
                    "__type__answer": {"status": "ok", "data": {"text/plain": "'int'"}},
                },
                {"answer": {"status": "ok", "type": "int"}},
            ),
            (
                "error_with_type_only",
                {
                    "__type__answer": {
                        "status": "error",
                        "ename": "NameError",
                        "evalue": "missing",
                        "traceback": ["traceback"],
                    }
                },
                {
                    "answer": {
                        "status": "error",
                        "ename": "NameError",
                        "evalue": "missing",
                        "traceback": ["traceback"],
                    }
                },
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
        payload_out: dict[str, Any] = {
            "status": "ok",
            "stdout": "hello",
            "stderr": "",
            "result": {"text/plain": "42"},
            "execution_count": 3,
            "error_name": None,
            "traceback": [],
            "user_expressions": {
                "__type__answer": {"status": "ok", "data": {"text/plain": "'int'"}},
            },
            "type": "result",
        }
        stream = _FakeSandboxStream(stdout_lines=[json.dumps(payload_out)], result=_FakeExecutionResult(stdout=""))
        sandbox = _FakeSandbox(_FakeExecutionResult(stdout=""), stream=stream)
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

    def test_execute_in_sandbox_handles_notebook_bridge_messages(self) -> None:
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
        marker = service._notebook_bridge_marker(handle)
        bridge_payload = {"call": "hogql_execute", "query": "select 1", "response_path": "/tmp/resp.json"}
        bridge_payload_json = json.dumps(bridge_payload)
        bridge_message = f"{marker}{len(bridge_payload_json)} {bridge_payload_json}\n"
        payload_out: dict[str, Any] = {
            "type": "result",
            "status": "ok",
            "stdout": f"before\n{bridge_message}after",
            "stderr": "",
            "result": None,
            "media": [],
            "execution_count": 1,
            "error_name": None,
            "traceback": [],
            "user_expressions": None,
        }
        stream = _FakeSandboxStream(
            stdout_lines=[
                json.dumps({"type": "stream", "name": "stdout", "text": bridge_message}),
                json.dumps(payload_out),
            ],
            result=_FakeExecutionResult(stdout=""),
        )
        sandbox = _FakeSandbox(_FakeExecutionResult(stdout=""), stream=stream)
        _FakeSandboxClass.sandbox = sandbox

        with (
            patch.object(service, "_get_sandbox_class", return_value=_FakeSandboxClass),
            patch.object(service, "_handle_notebook_bridge_payload") as mock_payload,
        ):
            execution_result = service._execute_in_sandbox(
                handle,
                "print('hi')",
                capture_variables=False,
                variable_names=[],
                timeout=5,
            )

        assert execution_result.stdout == "before\nafter"
        mock_payload.assert_called_once_with(bridge_payload_json, handle)

    def test_execute_in_sandbox_stream_yields_output_and_result(self) -> None:
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
        marker = service._notebook_bridge_marker(handle)
        bridge_payload = {"call": "hogql_execute", "query": "select 1", "response_path": "/tmp/resp.json"}
        bridge_payload_json = json.dumps(bridge_payload)
        bridge_message = f"{marker}{len(bridge_payload_json)} {bridge_payload_json}\n"
        payload_out: dict[str, Any] = {
            "type": "result",
            "status": "ok",
            "stdout": "final",
            "stderr": "",
            "result": None,
            "media": [],
            "execution_count": 2,
            "error_name": None,
            "traceback": [],
            "user_expressions": None,
        }
        stream = _FakeSandboxStream(
            stdout_lines=[
                json.dumps(
                    {
                        "type": "stream",
                        "name": "stdout",
                        "text": f"hello\n{bridge_message}world",
                    }
                ),
                json.dumps({"type": "stream", "name": "stderr", "text": "oops"}),
                json.dumps(payload_out),
            ],
            result=_FakeExecutionResult(stdout=""),
        )
        sandbox = _FakeSandbox(_FakeExecutionResult(stdout=""), stream=stream)
        _FakeSandboxClass.sandbox = sandbox

        with (
            patch.object(service, "_get_sandbox_class", return_value=_FakeSandboxClass),
            patch.object(service, "_handle_notebook_bridge_payload") as mock_payload,
        ):
            output = list(
                service._execute_in_sandbox_stream(
                    handle,
                    "print('hi')",
                    capture_variables=False,
                    variable_names=[],
                    timeout=5,
                )
            )

        assert output[0] == {"type": "stdout", "text": "hello\nworld"}
        assert output[1] == {"type": "stderr", "text": "oops"}
        assert output[2]["type"] == "result"
        assert output[2]["data"]["stdout"] == "final"
        mock_payload.assert_called_once_with(bridge_payload_json, handle)
        assert sandbox.timeout_seconds == 5

    @parameterized.expand(
        [
            (
                "no_marker_immediate",
                "__NOTEBOOK_BRIDGE__",
                ["hello12\n"],
                ["hello12\n"],
                [],
            ),
            (
                "marker_not_at_line_start",
                "__NOTEBOOK_BRIDGE__",
                ['hello __NOTEBOOK_BRIDGE__41 {"call":"hogql_execute","query":"select"}\n'],
                ['hello __NOTEBOOK_BRIDGE__41 {"call":"hogql_execute","query":"select"}\n'],
                [],
            ),
            (
                "payload_extraction",
                "__NOTEBOOK_BRIDGE__",
                [
                    '__NOTEBOOK_BRIDGE__41 {"call":"hogql_execute","query":"select"}\nworld\n',
                ],
                ["world\n"],
                ['{"call":"hogql_execute","query":"select"}'],
            ),
            (
                "payload_split_across_chunks",
                "__NOTEBOOK_BRIDGE__",
                [
                    '__NOTEBOOK_BRIDGE__41 {"call":"hogql_execute",',
                    '"query":"select"}\nnext\n',
                ],
                ["", "next\n"],
                ['{"call":"hogql_execute","query":"select"}'],
            ),
        ]
    )
    def test_notebook_bridge_parser_streaming(
        self,
        _name: str,
        marker: str,
        chunks: list[str],
        expected_outputs: list[str],
        expected_payloads: list[str],
    ) -> None:
        parser = _NotebookBridgeParser(marker=marker)
        outputs: list[str] = []
        payloads: list[str] = []
        for chunk in chunks:
            output, new_payloads = parser.feed(chunk)
            outputs.append(output)
            payloads.extend(new_payloads)

        assert outputs == expected_outputs
        assert payloads == expected_payloads
        assert parser.buffer == ""
