from collections.abc import Iterable
from dataclasses import replace
from typing import Any, cast

import pytest

from requests_mock import Mocker

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import build_default_schemas
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.turso import TursoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.turso.source import TursoSource


def test_permission_denial_disables_only_the_affected_table(requests_mock: Mocker, config: TursoSourceConfig) -> None:
    requests_mock.get("https://api.turso.tech/v1/organizations/example-org/databases", json={"databases": []})
    requests_mock.get(
        "https://api.turso.tech/v1/organizations/example-org/members", status_code=403, json={"error": "Forbidden"}
    )
    source = TursoSource()
    permissions = source.get_endpoint_permissions(config, 1, ["databases", "members"])
    assert permissions["databases"] is None
    assert permissions["members"] is not None and "permissions" in permissions["members"]
    defaults = build_default_schemas(source.get_schemas(config, 1, names=["databases", "members"]), permissions)
    assert {schema["name"]: schema["should_sync"] for schema in defaults} == {"databases": True, "members": False}


@pytest.mark.parametrize("organization", ["", "../other-org", "https://example.com", "example-org?x=y", " org "])
def test_invalid_organization_never_sends_credentials(
    requests_mock: Mocker, config: TursoSourceConfig, inputs: SourceInputs, organization: str
) -> None:
    config = replace(config, organization_slug=organization)
    source = TursoSource()
    valid, message = source.validate_credentials(config, team_id=1)
    assert valid is False
    assert message is not None and "organization slug" in message
    response = source.source_for_pipeline(config, source.get_resumable_source_manager(inputs), inputs)
    with pytest.raises(ValueError, match="organization slug"):
        list(cast(Iterable[Any], response.items()))
    assert requests_mock.call_count == 0


def test_unknown_table_fails_before_http(
    requests_mock: Mocker, config: TursoSourceConfig, inputs: SourceInputs
) -> None:
    source = TursoSource()
    with pytest.raises(ValueError, match="Unknown Turso table"):
        source.source_for_pipeline(
            config, source.get_resumable_source_manager(inputs), replace(inputs, schema_name="unknown")
        )
    assert requests_mock.call_count == 0
