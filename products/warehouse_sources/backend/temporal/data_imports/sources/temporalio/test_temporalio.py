import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from django.test import override_settings

from google.protobuf.duration_pb2 import Duration
from google.protobuf.timestamp_pb2 import Timestamp
from temporalio.api.activity.v1 import ActivityExecutionListInfo
from temporalio.api.common.v1 import ActivityType, Payload, SearchAttributes, WorkflowExecution, WorkflowType
from temporalio.api.enums.v1 import ActivityExecutionStatus, NamespaceState
from temporalio.api.namespace.v1 import NamespaceConfig, NamespaceInfo
from temporalio.api.schedule.v1 import ScheduleActionResult, ScheduleListEntry, ScheduleListInfo
from temporalio.api.workflowservice.v1 import (
    DescribeNamespaceResponse,
    ListActivityExecutionsResponse,
    ListNamespacesResponse,
    ListSchedulesResponse,
)
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.codec import EncryptionCodec

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import HostNotAllowedError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import SourceDriver
from products.warehouse_sources.backend.temporal.data_imports.sources.common.tests.resolver import addrinfo, resolver
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.temporalio import (
    TemporalIOSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.source import TemporalIOSource
from products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.temporalio import (
    FakeSettings,
    TemporalIOResumeConfig,
    _async_iter_to_sync,
    _ByteBudget,
    _encode_page_token,
    _estimate_size_bytes,
    _get_temporal_client,
    _paged_rows,
    _ResumePoint,
    _with_transient_rpc_retry,
)

_MIXINS_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins"
_TEMPORALIO_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.temporalio"


def _rpc_error(message: str, status: RPCStatusCode) -> RPCError:
    return RPCError(message, status, b"")


def _payload(**overrides: str) -> dict[str, str]:
    return {
        "host": "temporal.example.com",
        "port": "7233",
        "namespace": "namespace",
        "server_client_root_ca": "ca",
        "client_certificate": "cert",
        "client_private_key": "key",
        **overrides,
    }


def _config(**overrides: str) -> TemporalIOSourceConfig:
    return TemporalIOSourceConfig.from_dict(_payload(**overrides))


class TestTemporalIOClient:
    def test_fake_settings_satisfies_encryption_codec_contract(self):
        # FakeSettings must expose every attribute EncryptionCodec.from_settings reads
        # (TEST, DEBUG, TEMPORAL_SECRET_KEY, TEMPORAL_FALLBACK_SECRET_KEYS); a missing one raises
        # AttributeError. The 32-byte key clears the prod (TEST=False) length guard.
        codec = EncryptionCodec.from_settings(FakeSettings(TEMPORAL_SECRET_KEY="k" * 32))

        assert isinstance(codec, EncryptionCodec)

    async def test_get_temporal_client_builds_encryption_codec(self):
        config = _config(encryption_key="k" * 32)

        with patch.object(Client, "connect", new=AsyncMock(return_value=MagicMock())) as mock_connect:
            await _get_temporal_client(config, team_id=999)

        data_converter = mock_connect.call_args.kwargs["data_converter"]
        assert isinstance(data_converter.payload_codec, EncryptionCodec)

    @pytest.mark.parametrize("resolved_ip", ["169.254.169.254", "10.0.0.5"])
    async def test_a_host_resolving_to_an_internal_ip_is_refused_before_dialling(self, resolved_ip):
        with (
            override_settings(CLOUD_DEPLOYMENT="US"),
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", return_value=addrinfo(0, resolved_ip)),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch.object(Client, "connect", new=AsyncMock(return_value=MagicMock())) as mock_connect,
        ):
            with pytest.raises(HostNotAllowedError):
                await _get_temporal_client(_config(), team_id=999)

        mock_connect.assert_not_called()

    @pytest.mark.parametrize(
        "host,resolved,expected_target,expected_tls_domain",
        [
            ("temporal.example.com", "93.184.216.34", "93.184.216.34:7233", "temporal.example.com"),
            ("93.184.216.34", "93.184.216.34", "93.184.216.34:7233", None),
            ("2606:4700:4700::1111", "2606:4700:4700::1111", "[2606:4700:4700::1111]:7233", None),
            ("[2606:4700:4700::1111]", "2606:4700:4700::1111", "[2606:4700:4700::1111]:7233", None),
            ("2606:4700:4700:0::1111", "2606:4700:4700::1111", "[2606:4700:4700::1111]:7233", None),
        ],
    )
    async def test_the_checked_address_is_dialled_and_only_a_name_carries_tls(
        self, host, resolved, expected_target, expected_tls_domain
    ):
        # An address has no name of its own for the certificate, however it is written.
        with (
            override_settings(CLOUD_DEPLOYMENT="US"),
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", side_effect=resolver(resolved)),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch.object(Client, "connect", new=AsyncMock(return_value=MagicMock())) as mock_connect,
        ):
            await _get_temporal_client(_config(host=host), team_id=999)

        assert mock_connect.call_args.args[0] == expected_target
        assert mock_connect.call_args.kwargs["tls"].domain == expected_tls_domain

    @pytest.mark.parametrize("port", ["7233@169.254.169.254:80", "not-a-port"])
    def test_a_port_that_is_not_a_number_is_rejected(self, port):
        # `connect()` builds the dial target from host and port, so a port that carries anything
        # but a number moves the target past the host check.
        is_valid, errors = TemporalIOSource().validate_config(_payload(port=port))

        assert not is_valid
        assert errors

    @pytest.mark.parametrize(
        "host,resolved,expected_valid",
        [
            ("temporal.example.com", "10.0.0.5", False),
            ("[2606:4700:4700::1111]", "2606:4700:4700::1111", True),
        ],
    )
    def test_creating_a_source_checks_the_host(self, host, resolved, expected_valid):
        with (
            override_settings(CLOUD_DEPLOYMENT="US"),
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", side_effect=resolver(resolved)),
            patch(f"{_MIXINS_MODULE}.logger"),
        ):
            is_valid, error = TemporalIOSource().validate_credentials(_config(host=host), team_id=999)

        assert is_valid is expected_valid
        assert (error is None) is expected_valid


class TestTransientRPCRetry:
    @pytest.mark.parametrize(
        "message,status",
        [
            ("namespace rate limit exceeded", RPCStatusCode.RESOURCE_EXHAUSTED),
            ("downstream duration timeout", RPCStatusCode.DEADLINE_EXCEEDED),
            ("dns error", RPCStatusCode.UNAVAILABLE),
            # tonic's generic fallback for a broken connection — UNKNOWN with no more specific
            # h2/cancellation detail available — must still be ridden out in-process.
            ("transport error", RPCStatusCode.UNKNOWN),
        ],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.temporalio.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_persistent_transient_error_is_reraised(self, sleep, message, status):
        async def operation():
            raise _rpc_error(message, status)

        with pytest.raises(RPCError):
            await _with_transient_rpc_retry(operation, MagicMock(), max_attempts=4)

        # Bounded attempts leave Temporal to retry; backs off between attempts but not after the last.
        assert sleep.await_args_list == [call(2), call(4), call(6)]

    @pytest.mark.parametrize(
        "message,status",
        [
            ("workflow execution not found for", RPCStatusCode.NOT_FOUND),
            # UNKNOWN alone must not be retried — only UNKNOWN carrying a transport signature is.
            ("internal server error", RPCStatusCode.UNKNOWN),
            # CANCELLED alone must not be retried — only the "Timeout expired" and "operation was
            # canceled" phrases qualify.
            ("Cancelled by caller", RPCStatusCode.CANCELLED),
        ],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.temporalio.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_non_transient_rpc_error_is_not_retried(self, sleep, message, status):
        async def operation():
            raise _rpc_error(message, status)

        with pytest.raises(RPCError):
            await _with_transient_rpc_retry(operation, MagicMock())

        assert sleep.await_count == 0


class TestEstimateSizeBytes:
    def test_counts_strings_nested_below_the_top_level(self):
        payload = "x" * 10_000
        nested = {"events": [{"input": {"payload": payload}}]}

        assert _estimate_size_bytes(nested) >= len(payload)


class TestByteBudget:
    def test_release_frees_capacity_for_a_blocked_item(self):
        budget = _ByteBudget(max_bytes=100)
        budget.reserve(100)
        assert budget._admits(100) is False

        budget.release(100)

        assert budget.in_flight_bytes == 0
        assert budget._admits(100) is True


class TestAsyncIterToSync:
    @staticmethod
    async def _aiter(items):
        for item in items:
            yield item

    def test_propagates_a_producer_exception_to_the_consumer(self):
        async def failing():
            yield {"id": 1}
            raise RuntimeError("boom")

        stream = _async_iter_to_sync(failing())

        assert next(stream) == {"id": 1}
        with pytest.raises(RuntimeError, match="boom"):
            next(stream)

    def test_reserves_and_releases_stay_balanced(self):
        # Catches both halves of the accounting. A reservation the consumer never releases leaks
        # until the producer blocks on a budget that only fills; an item enqueued without reserving
        # never counts against the cap at all, which is the unbounded behavior this bound replaced.
        budgets = []

        def _record(max_bytes):
            budgets.append(_ByteBudget(max_bytes))
            return budgets[-1]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.temporalio._ByteBudget",
            side_effect=_record,
        ):
            # A cap every item fits under, so a missing release surfaces as leftover in-flight bytes
            # rather than a producer that blocks and hangs the test.
            items = [{"payload": "x" * 100} for _ in range(10)]
            assert list(_async_iter_to_sync(self._aiter(items), max_bytes=100_000)) == items

        assert budgets[0].in_flight_bytes == 0

    def test_resume_points_are_charged_by_their_page_token_size(self):
        reserved: list[int] = []
        original_reserve = _ByteBudget.reserve

        def _spy(budget, size):
            reserved.append(size)
            original_reserve(budget, size)

        token = "t" * 1000
        saved: list[TemporalIOResumeConfig] = []
        items = [_ResumePoint(state=TemporalIOResumeConfig(next_page_token=token)), {"id": 1}]
        with patch.object(_ByteBudget, "reserve", _spy):
            assert list(_async_iter_to_sync(self._aiter(items), save_resume_state=saved.append)) == [{"id": 1}]

        assert reserved[0] == len(token)
        assert [state.next_page_token for state in saved] == [token]


def _timestamp(value: datetime.datetime) -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(value)
    return ts


def _keyword_search_attributes(**values: str) -> SearchAttributes:
    return SearchAttributes(
        indexed_fields={
            key: Payload(metadata={"encoding": b"json/plain", "type": b"Keyword"}, data=f'"{value}"'.encode())
            for key, value in values.items()
        }
    )


def _schedules_page(schedule_ids: list[str], next_page_token: bytes = b"") -> ListSchedulesResponse:
    return ListSchedulesResponse(
        schedules=[
            ScheduleListEntry(
                schedule_id=schedule_id,
                search_attributes=_keyword_search_attributes(Team="billing"),
                info=ScheduleListInfo(
                    workflow_type=WorkflowType(name="NightlyExport"),
                    paused=True,
                    recent_actions=[
                        ScheduleActionResult(
                            start_workflow_result=WorkflowExecution(workflow_id=f"{schedule_id}-run", run_id="r-1")
                        )
                    ],
                ),
            )
            for schedule_id in schedule_ids
        ],
        next_page_token=next_page_token,
    )


def _activities_page(activity_ids: list[str], next_page_token: bytes = b"") -> ListActivityExecutionsResponse:
    return ListActivityExecutionsResponse(
        executions=[ActivityExecutionListInfo(activity_id=activity_id, run_id="r-1") for activity_id in activity_ids],
        next_page_token=next_page_token,
    )


def _namespace(name: str) -> DescribeNamespaceResponse:
    return DescribeNamespaceResponse(
        namespace_info=NamespaceInfo(name=name, id=f"{name}-id", state=NamespaceState.NAMESPACE_STATE_REGISTERED),
        config=NamespaceConfig(workflow_execution_retention_ttl=Duration(seconds=259200)),
    )


def _drive(schema_name: str, workflow_service: MagicMock, **run_kwargs):
    client = MagicMock()
    client.workflow_service = workflow_service
    with patch(f"{_TEMPORALIO_MODULE}._get_temporal_client", new=AsyncMock(return_value=client)):
        return SourceDriver(TemporalIOSource(), _config()).run(schema_name, [], **run_kwargs)


def _page_tokens(rpc: AsyncMock) -> list[bytes]:
    return [rpc_call.args[0].next_page_token for rpc_call in rpc.await_args_list]


class TestPagedListTables:
    @pytest.mark.parametrize(
        "schema_name,rpc_name,id_field,make_page",
        [
            ("schedules", "list_schedules", "id", _schedules_page),
            ("standalone_activities", "list_activity_executions", "activity_id", _activities_page),
        ],
    )
    @pytest.mark.parametrize(
        "resume_token,expected_tokens,expected_ids",
        [
            (None, [b"", b"page-2"], ["a", "b", "c"]),
            (b"page-2", [b"page-2"], ["c"]),
        ],
    )
    def test_walks_every_page_and_resumes_from_the_saved_token(
        self, schema_name, rpc_name, id_field, make_page, resume_token, expected_tokens, expected_ids
    ):
        pages = {b"": make_page(["a", "b"], b"page-2"), b"page-2": make_page(["c"])}
        rpc = AsyncMock(side_effect=lambda request, **kwargs: pages[request.next_page_token])
        service = MagicMock(**{rpc_name: rpc})
        resume_state = (
            TemporalIOResumeConfig(next_page_token=_encode_page_token(resume_token)) if resume_token else None
        )

        result = _drive(schema_name, service, resume_state=resume_state)

        assert result.raised is None
        assert [row[id_field] for row in result.rows] == expected_ids
        assert _page_tokens(rpc) == expected_tokens
        assert all(rpc_call.args[0].namespace == "namespace" for rpc_call in rpc.await_args_list)
        assert result.final_state == TemporalIOResumeConfig(next_page_token=_encode_page_token(b"page-2"))

    async def test_stages_the_next_page_token_before_handing_on_the_whole_page(self):
        pages = {b"": _activities_page(["a", "b"], b"page-2"), b"page-2": _activities_page(["c"])}
        manager = MagicMock(**{"can_resume.return_value": False})

        items = [
            item
            async for item in _paged_rows(
                AsyncMock(side_effect=lambda token: pages[token]),
                lambda response: ({"id": info.activity_id} for info in response.executions),
                manager,
                MagicMock(),
            )
        ]

        # A resume after the first page is written starts at page 2, so a full refresh appends no row twice.
        assert items == [
            _ResumePoint(state=TemporalIOResumeConfig(next_page_token=_encode_page_token(b"page-2"))),
            [{"id": "a"}, {"id": "b"}],
            [{"id": "c"}],
        ]

    def test_schedule_rows_carry_the_workflow_type_recent_runs_and_search_attributes(self):
        service = MagicMock(list_schedules=AsyncMock(return_value=_schedules_page(["nightly"])))

        [row] = _drive("schedules", service).rows

        assert row["id"] == "nightly"
        assert row["workflow_type"] == "NightlyExport"
        assert row["paused"] is True
        assert row["recent_actions"][0]["start_workflow_result"] == {"workflow_id": "nightly-run", "run_id": "r-1"}
        assert row["search_attributes"] == {"Team": ["billing"]}
        assert "memo" not in row

    @pytest.mark.parametrize(
        "closed,expected_close_time,expected_duration",
        [
            (True, datetime.datetime(2026, 1, 2, 3, 5, tzinfo=datetime.UTC), "60s"),
            (False, None, None),
        ],
    )
    def test_activity_rows_use_datetimes_and_status_names(self, closed, expected_close_time, expected_duration):
        scheduled = datetime.datetime(2026, 1, 2, 3, 4, tzinfo=datetime.UTC)
        info = ActivityExecutionListInfo(
            activity_id="charge-card",
            run_id="r-1",
            activity_type=ActivityType(name="ChargeCard"),
            schedule_time=_timestamp(scheduled),
            status=ActivityExecutionStatus.ACTIVITY_EXECUTION_STATUS_RUNNING,
            search_attributes=_keyword_search_attributes(Region="eu"),
        )
        if closed:
            info.close_time.CopyFrom(_timestamp(expected_close_time))
            info.execution_duration.CopyFrom(Duration(seconds=60))
            info.status = ActivityExecutionStatus.ACTIVITY_EXECUTION_STATUS_COMPLETED
        service = MagicMock(
            list_activity_executions=AsyncMock(return_value=ListActivityExecutionsResponse(executions=[info]))
        )

        [row] = _drive("standalone_activities", service).rows

        assert row["activity_type"] == "ChargeCard"
        assert row["schedule_time"] == scheduled
        assert row["close_time"] == expected_close_time
        assert row.get("execution_duration") == expected_duration
        assert row["status"] == (
            "ACTIVITY_EXECUTION_STATUS_COMPLETED" if closed else "ACTIVITY_EXECUTION_STATUS_RUNNING"
        )
        assert row["search_attributes"] == {"Region": ["eu"]}


class TestNamespaces:
    def test_lists_every_namespace_with_its_info_at_the_row_root(self):
        pages = {
            b"": ListNamespacesResponse(namespaces=[_namespace("orders")], next_page_token=b"page-2"),
            b"page-2": ListNamespacesResponse(namespaces=[_namespace("billing")]),
        }
        list_namespaces = AsyncMock(side_effect=lambda request, **kwargs: pages[request.next_page_token])
        describe_namespace = AsyncMock()
        service = MagicMock(list_namespaces=list_namespaces, describe_namespace=describe_namespace)

        result = _drive("namespaces", service)

        assert result.raised is None
        assert [(row["id"], row["name"], row["state"]) for row in result.rows] == [
            ("orders-id", "orders", "NAMESPACE_STATE_REGISTERED"),
            ("billing-id", "billing", "NAMESPACE_STATE_REGISTERED"),
        ]
        assert result.rows[0]["config"]["workflow_execution_retention_ttl"] == "259200s"
        assert _page_tokens(list_namespaces) == [b"", b"page-2"]
        describe_namespace.assert_not_awaited()

    @pytest.mark.parametrize("status", [RPCStatusCode.PERMISSION_DENIED, RPCStatusCode.UNIMPLEMENTED])
    def test_a_refused_listing_falls_back_to_the_configured_namespace(self, status):
        describe_namespace = AsyncMock(return_value=_namespace("namespace"))
        service = MagicMock(
            list_namespaces=AsyncMock(side_effect=_rpc_error("Request unauthorized.", status)),
            describe_namespace=describe_namespace,
        )

        result = _drive("namespaces", service)

        assert result.raised is None
        assert [row["name"] for row in result.rows] == ["namespace"]
        describe_namespace.assert_awaited_once()
        assert describe_namespace.await_args_list[0].args[0].namespace == "namespace"

    @pytest.mark.parametrize(
        "side_effect",
        [
            # Falling back after rows were yielded would replace a partial listing with one namespace.
            [
                ListNamespacesResponse(namespaces=[_namespace("orders")], next_page_token=b"page-2"),
                _rpc_error("Request unauthorized.", RPCStatusCode.PERMISSION_DENIED),
            ],
            [_rpc_error("bad request", RPCStatusCode.INVALID_ARGUMENT)],
        ],
    )
    def test_other_listing_failures_are_raised(self, side_effect):
        describe_namespace = AsyncMock()
        service = MagicMock(list_namespaces=AsyncMock(side_effect=side_effect), describe_namespace=describe_namespace)

        result = _drive("namespaces", service)

        assert isinstance(result.raised, RPCError)
        describe_namespace.assert_not_awaited()
