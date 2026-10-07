import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import responses
import structlog
from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.partitioning import (
    append_partition_key_to_table,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pinecone import (
    PineconeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pinecone.source import PineconeSource

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse


def source_inputs(endpoint: str) -> SourceInputs:
    return SourceInputs(
        schema_name=endpoint,
        schema_id="fake-schema",
        source_id="fake-source",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value="2099-01-01T00:00:00Z",
        db_incremental_field_earliest_value=None,
        incremental_field="created_at",
        incremental_field_type=None,
        job_id="fake-job",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


def pipeline(endpoint: str) -> "SourceResponse":
    source = PineconeSource()
    inputs = source_inputs(endpoint)
    return source.source_for_pipeline(
        PineconeSourceConfig(api_key="fake-pinecone-key"), source.get_resumable_source_manager(inputs), inputs
    )


def sync_items(response: "SourceResponse") -> Iterable[Any]:
    items = response.items()
    assert isinstance(items, Iterable)
    return items


class TestPineconeTransport(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "indexes",
                "indexes",
                "name",
                {"name": "sample-index", "schema": {"fields": {}}, "status": {"ready": True}},
            ),
            ("collections", "collections", "name", {"name": "sample-collection", "dimension": 3, "status": "Ready"}),
            (
                "backups",
                "data",
                "backup_id",
                {"backup_id": "fake-backup", "created_at": "2026-08-01T00:00:00Z", "record_count": 3},
            ),
            (
                "restore_jobs",
                "data",
                "restore_job_id",
                {"restore_job_id": "fake-restore", "created_at": None, "status": "Pending"},
            ),
        ]
    )
    def test_full_refresh_preserves_inventory_rows(
        self, endpoint: str, selector: str, primary_key: str, row: dict[str, object]
    ) -> None:
        redis = MagicMock()
        redis.exists.return_value = 0
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable.get_client",
                return_value=redis,
            ),
            responses.RequestsMock() as http,
        ):
            path = endpoint.replace("_", "-")
            http.add(responses.GET, f"https://api.pinecone.io/{path}", json={selector: [row]})
            response = pipeline(endpoint)
            assert list(sync_items(response)) == [[row]]
            assert response.name == endpoint
            assert response.primary_keys == [primary_key]
            assert response.partition_keys == ["created_at" if endpoint == "backups" else primary_key]
            assert response.sort_mode is None
            partitioned = append_partition_key_to_table(
                table_from_py_list([row]),
                partition_count=response.partition_count,
                partition_size=response.partition_size,
                partition_keys=response.partition_keys,
                partition_mode=response.partition_mode,
                partition_format=response.partition_format,
                logger=structlog.get_logger(),
            )
            assert partitioned is not None and partitioned.table.num_rows == 1
            request = http.calls[0].request
            assert request.headers["Api-Key"] == "fake-pinecone-key"
            assert request.headers["X-Pinecone-Api-Version"] == "2026-07"
            expected_params = {"limit": ["100"]} if endpoint in ("backups", "restore_jobs") else {}
            assert parse_qs(urlsplit(request.url or "").query) == expected_params
            assert len(http.calls) == 1
            redis.set.assert_not_called()

    @parameterized.expand(
        [
            ("backups", "absent", {}),
            ("backups", "null", {"pagination": None}),
            ("restore_jobs", "absent", {}),
            ("restore_jobs", "null", {"pagination": None}),
            ("restore_jobs", "empty_token", {"pagination": {"next": ""}}),
        ]
    )
    def test_cursor_pages_checkpoint_after_yield_and_stop(
        self, endpoint: str, _name: str, terminal: dict[str, object]
    ) -> None:
        redis = MagicMock()
        redis.exists.return_value = 0
        inputs = source_inputs(endpoint)
        source = PineconeSource()
        manager = source.get_resumable_source_manager(inputs)
        path = endpoint.replace("_", "-")
        key = "backup_id" if endpoint == "backups" else "restore_job_id"
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable.get_client",
                return_value=redis,
            ),
            responses.RequestsMock() as http,
        ):
            http.add(
                responses.GET,
                f"https://api.pinecone.io/{path}",
                json={"data": [{key: "first"}], "pagination": {"next": "next+/="}},
            )
            http.add(
                responses.GET,
                f"https://api.pinecone.io/{path}",
                json={"data": [{key: "second"}], "pagination": {"next": "last-token"}},
            )
            http.add(responses.GET, f"https://api.pinecone.io/{path}", json={"data": [{key: "third"}], **terminal})
            response = source.source_for_pipeline(PineconeSourceConfig(api_key="fake-pinecone-key"), manager, inputs)
            pages = iter(sync_items(response))
            assert next(pages) == [{key: "first"}]
            assert not manager.has_staged_state()
            assert next(pages) == [{key: "second"}]
            manager.commit()
            assert json.loads(redis.set.call_args.args[1]) == {"cursor": "next+/="}
            assert next(pages) == [{key: "third"}]
            manager.commit()
            assert json.loads(redis.set.call_args.args[1]) == {"cursor": "last-token"}
            assert list(pages) == []
            assert not manager.has_staged_state()
            assert redis.set.call_count == 2
            assert [parse_qs(urlsplit(call.request.url or "").query).get("paginationToken") for call in http.calls] == [
                None,
                ["next+/="],
                ["last-token"],
            ]

    @parameterized.expand([("backups",), ("restore_jobs",)])
    def test_resume_uses_saved_token(self, endpoint: str) -> None:
        redis = MagicMock()
        redis.exists.return_value = 1
        redis.get.return_value = b'{"cursor":"saved-token"}'
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable.get_client",
                return_value=redis,
            ),
            responses.RequestsMock() as http,
        ):
            http.add(
                responses.GET,
                f"https://api.pinecone.io/{endpoint.replace('_', '-')}",
                json={"data": [{"name": "resumed"}]},
            )
            assert list(sync_items(pipeline(endpoint))) == [[{"name": "resumed"}]]
            assert parse_qs(urlsplit(http.calls[0].request.url or "").query) == {
                "limit": ["100"],
                "paginationToken": ["saved-token"],
            }
            redis.set.assert_not_called()

    @parameterized.expand(
        [("indexes", "indexes"), ("collections", "collections"), ("backups", "data"), ("restore_jobs", "data")]
    )
    def test_empty_inventory_is_valid(self, endpoint: str, selector: str) -> None:
        redis = MagicMock()
        redis.exists.return_value = 0
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable.get_client",
                return_value=redis,
            ),
            responses.RequestsMock() as http,
        ):
            http.add(responses.GET, f"https://api.pinecone.io/{endpoint.replace('_', '-')}", json={selector: []})
            assert list(sync_items(pipeline(endpoint))) == []
            assert len(http.calls) == 1

    def test_unexpected_envelope_fails_instead_of_erasing_inventory(self) -> None:
        with responses.RequestsMock() as http:
            http.add(responses.GET, "https://api.pinecone.io/indexes", json={"unexpected": []})
            with self.assertRaises(ValueError):
                list(sync_items(pipeline("indexes")))

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_authentication_errors_are_terminal(self, _name: str, status: int) -> None:
        with responses.RequestsMock() as http:
            http.add(responses.GET, "https://api.pinecone.io/indexes", json={"error": "denied"}, status=status)
            with self.assertRaises(HTTPError) as caught:
                list(sync_items(pipeline("indexes")))
            assert any(pattern in str(caught.exception) for pattern in PineconeSource().get_non_retryable_errors())
            assert "fake-pinecone-key" not in str(caught.exception)
            assert len(http.calls) == 1

    @parameterized.expand([("throttled", 429), ("internal_error", 500), ("bad_gateway", 502), ("unavailable", 503)])
    def test_transient_status_retries_through_shared_transport(self, _name: str, status: int) -> None:
        with responses.RequestsMock() as http:
            http.add(
                responses.GET,
                "https://api.pinecone.io/indexes",
                json={"error": "transient"},
                status=status,
                headers={"Retry-After": "0"},
            )
            http.add(responses.GET, "https://api.pinecone.io/indexes", json={"indexes": [{"name": "sample-index"}]})
            assert list(sync_items(pipeline("indexes"))) == [[{"name": "sample-index"}]]
            assert len(http.calls) == 2

    def test_unknown_endpoint_fails_before_http(self) -> None:
        with responses.RequestsMock() as http:
            with self.assertRaises(UnknownResourceError):
                pipeline("vectors")
            assert len(http.calls) == 0
