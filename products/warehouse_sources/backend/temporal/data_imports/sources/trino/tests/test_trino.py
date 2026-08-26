import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trino import (
    TrinoAuthTypeConfig,
    TrinoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trino.source import TrinoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino import (
    connect_trino,
    discover_trino_schemas,
)


def _config(**overrides: object) -> TrinoSourceConfig:
    values: dict[str, object] = {
        "host": "trino.example.com",
        "port": 443,
        "catalog": "hive",
        "schema": None,
        "use_ssl": True,
        "verify_ssl": True,
        "auth_type": TrinoAuthTypeConfig(user="posthog", selection="password", password="secret"),
    }
    values.update(overrides)
    return TrinoSourceConfig(**values)  # type: ignore[arg-type]


def test_connect_trino_uses_tracked_session_and_closes_resources() -> None:
    connection = MagicMock()
    session = MagicMock()

    with (
        patch("trino.dbapi.connect", return_value=connection) as mock_connect,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino.make_tracked_session",
            return_value=session,
        ) as mock_session,
        connect_trino(_config()) as opened,
    ):
        assert opened is connection

    mock_session.assert_called_once_with(redact_values=("secret",), allow_redirects=False)
    assert session.verify is True
    assert mock_connect.call_args.kwargs["host"] == "trino.example.com"
    assert mock_connect.call_args.kwargs["catalog"] == "hive"
    assert mock_connect.call_args.kwargs["http_scheme"] == "https"
    assert mock_connect.call_args.kwargs["http_session"] is session
    assert mock_connect.call_args.kwargs["verify"] is True
    connection.close.assert_called_once_with()
    session.close.assert_called_once_with()


def test_connect_trino_rejects_credentials_over_http() -> None:
    with pytest.raises(ValueError, match="require HTTPS"):
        with connect_trino(_config(use_ssl=False)):
            pass


def test_connect_trino_closes_tracked_session_when_connect_fails() -> None:
    session = MagicMock()

    with (
        patch("trino.dbapi.connect", side_effect=RuntimeError("connection failed")),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino.make_tracked_session",
            return_value=session,
        ),
        pytest.raises(RuntimeError, match="connection failed"),
        connect_trino(_config()),
    ):
        pass

    session.close.assert_called_once_with()


def test_discover_trino_schemas_groups_columns_and_filters_names() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        ("analytics", "events", "id", "bigint", "NO"),
        ("analytics", "events", "properties", "map(varchar, varchar)", "YES"),
        ("sales", "orders", "id", "bigint", "NO"),
    ]

    discovered = discover_trino_schemas(cursor, _config(), names=["analytics.events"])

    assert discovered == [
        (
            "hive",
            "analytics",
            "events",
            [("id", "bigint", False), ("properties", "map(varchar, varchar)", True)],
        )
    ]
    assert 'FROM "hive".information_schema.columns' in cursor.execute.call_args.args[0]


def test_trino_source_is_direct_only() -> None:
    source = TrinoSource()

    assert source.supports_scheduled_sync is False
    assert source.get_source_config.unreleasedSource is True
