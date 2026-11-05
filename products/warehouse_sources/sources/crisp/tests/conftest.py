import pytest

from products.warehouse_sources.sources.crisp._config import CrispSourceConfig


@pytest.fixture
def config() -> CrispSourceConfig:
    return CrispSourceConfig(
        website_id="00000000-0000-4000-8000-000000000001",
        token_identifier="example-identifier",
        token_key="example-key",
    )
