import pytest
from unittest.mock import MagicMock, call, patch

from parameterized import parameterized

from posthog.models import Organization

from products.managed_warehouse.backend import common
from products.managed_warehouse.backend.facade import api as warehouse_api
from products.managed_warehouse.backend.logic import connection
from products.managed_warehouse.backend.model_observability import DUCKGRES_SERVER_ACCESS_METRIC
from products.managed_warehouse.backend.models import DuckgresServer


def _server(organization: Organization, **overrides: object) -> DuckgresServer:
    return DuckgresServer.objects.create(
        organization=organization,
        host="warehouse.example.com",
        database="ducklake",
        username="root",
        password="example-password",
        **overrides,
    )


def _get_server(server_id: str) -> DuckgresServer:
    return DuckgresServer.objects.get(id=server_id)


def _metric_call(
    operation: str,
    accessor_function: str,
    *,
    caller_function: str | None = None,
    accessor_module: str = __name__,
    caller_module: str = __name__,
) -> object:
    return call(
        DUCKGRES_SERVER_ACCESS_METRIC,
        1,
        {
            "operation": operation,
            "accessor_module": accessor_module,
            "accessor_function": accessor_function,
            "caller_module": caller_module,
            "caller_function": caller_function or accessor_function,
        },
    )


@pytest.mark.django_db
class TestDuckgresServerModelObservability:
    def test_records_reads_when_the_query_executes_with_the_immediate_external_caller(self) -> None:
        organization = Organization.objects.create(name="Example organization")
        server = _server(organization)
        record_counter = MagicMock()

        with patch("products.managed_warehouse.backend.model_observability.record_counter", record_counter):
            queryset = DuckgresServer.objects.filter(id=server.id)
            record_counter.assert_not_called()

            assert list(queryset) == [server]
            assert list(queryset) == [server]
            _get_server(str(server.id))

        assert record_counter.call_args_list == [
            _metric_call("read", "test_records_reads_when_the_query_executes_with_the_immediate_external_caller"),
            _metric_call("read", "_get_server"),
        ]

    def test_records_the_real_common_accessor_and_the_business_caller(self) -> None:
        organization = Organization.objects.create(name="Example organization")
        server = _server(organization)
        record_counter = MagicMock()

        with (
            patch("products.managed_warehouse.backend.common.is_dev_mode", return_value=False),
            patch("products.managed_warehouse.backend.model_observability.record_counter", record_counter),
        ):
            assert common.get_duckgres_server_for_organization(str(organization.id)) == server

        record_counter.assert_called_once_with(
            DUCKGRES_SERVER_ACCESS_METRIC,
            1,
            {
                "operation": "read",
                "accessor_module": "products.managed_warehouse.backend.common",
                "accessor_function": "get_duckgres_server_for_organization",
                "caller_module": __name__,
                "caller_function": "test_records_the_real_common_accessor_and_the_business_caller",
            },
        )

    def test_skips_the_facade_when_identifying_the_business_caller(self) -> None:
        organization = Organization.objects.create(name="Example organization")
        _server(organization)
        record_counter = MagicMock()

        with patch("products.managed_warehouse.backend.model_observability.record_counter", record_counter):
            assert warehouse_api.has_provisioned_warehouse(organization.id)

        record_counter.assert_called_once_with(
            DUCKGRES_SERVER_ACCESS_METRIC,
            1,
            {
                "operation": "read",
                "accessor_module": "products.managed_warehouse.backend.facade.api",
                "accessor_function": "has_provisioned_warehouse",
                "caller_module": __name__,
                "caller_function": "test_skips_the_facade_when_identifying_the_business_caller",
            },
        )

    def test_skips_the_connection_gateway_when_identifying_the_business_caller(self) -> None:
        organization = Organization.objects.create(name="Example organization")
        _server(organization)
        record_counter = MagicMock()

        with patch("products.managed_warehouse.backend.model_observability.record_counter", record_counter):
            connection.update_managed_warehouse_root_password(
                organization_id=organization.id, password="replacement-password"
            )

        assert record_counter.call_args_list == [
            _metric_call(
                "read",
                "update_managed_warehouse_root_password",
                accessor_module="products.managed_warehouse.backend.logic.connection",
                caller_function="test_skips_the_connection_gateway_when_identifying_the_business_caller",
            ),
            _metric_call(
                "update",
                "update_managed_warehouse_root_password",
                accessor_module="products.managed_warehouse.backend.logic.connection",
                caller_function="test_skips_the_connection_gateway_when_identifying_the_business_caller",
            ),
        ]

    @parameterized.expand(["count", "exists", "iterator"])
    def test_records_query_execution_methods(self, query_operation: str) -> None:
        organization = Organization.objects.create(name="Example organization")
        server = _server(organization)
        record_counter = MagicMock()

        with patch("products.managed_warehouse.backend.model_observability.record_counter", record_counter):
            queryset = DuckgresServer.objects.filter(id=server.id)
            result = getattr(queryset, query_operation)()
            if query_operation == "iterator":
                assert list(result) == [server]
            else:
                assert result

        record_counter.assert_called_once_with(
            DUCKGRES_SERVER_ACCESS_METRIC,
            1,
            {
                "operation": "read",
                "accessor_module": __name__,
                "accessor_function": "test_records_query_execution_methods",
                "caller_module": __name__,
                "caller_function": "test_records_query_execution_methods",
            },
        )

    def test_records_create_update_and_delete_once_per_model_operation(self) -> None:
        organization = Organization.objects.create(name="Example organization")
        record_counter = MagicMock()

        with patch("products.managed_warehouse.backend.model_observability.record_counter", record_counter):
            server = _server(organization)
            server.host = "replacement.example.com"
            server.save(update_fields=["host"])
            DuckgresServer.objects.filter(id=server.id).update(port=6543)
            DuckgresServer.objects.filter(id=server.id).delete()

        assert record_counter.call_args_list == [
            _metric_call("create", "_server"),
            _metric_call("update", "test_records_create_update_and_delete_once_per_model_operation"),
            _metric_call("update", "test_records_create_update_and_delete_once_per_model_operation"),
            _metric_call("delete", "test_records_create_update_and_delete_once_per_model_operation"),
        ]

    def test_metrics_failures_do_not_interrupt_model_access(self) -> None:
        organization = Organization.objects.create(name="Example organization")
        server = _server(organization)
        record_counter = MagicMock(side_effect=RuntimeError("metrics unavailable"))

        with patch("products.managed_warehouse.backend.model_observability.record_counter", record_counter):
            assert DuckgresServer.objects.get(id=server.id) == server

    def test_documents_reads_that_bypass_the_default_manager(self) -> None:
        organization = Organization.objects.create(name="Example organization")
        server = _server(organization)
        organization = Organization.objects.get(id=organization.id)
        record_counter = MagicMock()

        with patch("products.managed_warehouse.backend.model_observability.record_counter", record_counter):
            assert DuckgresServer._base_manager.get(id=server.id) == server
            assert organization.duckgres_server == server
            assert (
                Organization.objects.select_related("duckgres_server").get(id=organization.id).duckgres_server == server
            )
            assert (
                Organization.objects.prefetch_related("duckgres_server").get(id=organization.id).duckgres_server
                == server
            )

        record_counter.assert_not_called()
