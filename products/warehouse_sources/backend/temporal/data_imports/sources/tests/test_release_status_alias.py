from products.warehouse_sources.backend.facade.source_config import ReleaseStatus, SourceConfigResponse


def test_alpha_is_an_alias_of_beta():
    # Lookup by name, so mypy does not treat the two members as distinct literals.
    assert ReleaseStatus["ALPHA"] is ReleaseStatus.BETA
    assert [status.value for status in ReleaseStatus] == ["beta", "ga"]


def test_openapi_enum_lists_each_status_once():
    schema = SourceConfigResponse.model_json_schema()["$defs"]["ReleaseStatus"]
    assert schema["enum"] == ["beta", "ga"]
