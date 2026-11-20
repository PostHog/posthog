import pytest

from products.warehouse_sources.backend.facade.contracts import ConfigValueError, UndecryptedConfigError
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postgres import (
    PostgresSourceConfig,
)

# The generic runtime tests live in packages/typed-config/tests. These cover how warehouse sources use it.

_UNDECRYPTED_TOKEN = (
    "gAAAAABqTJ0OKLTREfglaXr0DZrJ4eYT7GVcKeA0avLvEzY7k3ll0JuD8VpL--DGJ9Dbt9y3KwyAolvAXit1ceqyuOzwyjTqlg=="
)


def test_repr_redacts_real_postgres_source_config():
    cfg = PostgresSourceConfig(
        host="fadevpn-11499.example.cloud",
        database="defaultdb",
        user="datawarehouse",
        password="hunter2",
        port=26257,
    )

    rendered = repr(cfg)
    assert "hunter2" not in rendered
    assert "password='***'" in rendered
    # Connection metadata stays visible for debugging.
    assert "host='fadevpn-11499.example.cloud'" in rendered


@pytest.mark.parametrize(
    "port,expected_error",
    [
        ("not-a-number", ConfigValueError),
        (_UNDECRYPTED_TOKEN, UndecryptedConfigError),
    ],
)
def test_generated_config_raises_the_facade_error_classes(port, expected_error):
    # Callers catch these classes from the facade, so the runtime must raise the same classes.
    with pytest.raises(expected_error):
        PostgresSourceConfig.from_dict(
            {"host": "db.example.com", "database": "db", "user": "reader", "password": "hunter2", "port": port}
        )
