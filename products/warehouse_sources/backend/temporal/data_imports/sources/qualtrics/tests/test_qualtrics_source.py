import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qualtrics import (
    QualtricsAuthMethodConfig,
    QualtricsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualtrics import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.qualtrics.qualtrics import QualtricsCredentials

EXPECTED_ENDPOINTS = {
    "surveys",
    "users",
    "groups",
    "divisions",
    "distributions",
    "survey_questions",
    "survey_responses",
}


def _config(selection: str = "api_token") -> QualtricsSourceConfig:
    return QualtricsSourceConfig(
        datacenter_id="iad1",
        auth_method=QualtricsAuthMethodConfig(
            selection=selection,  # type: ignore[arg-type]
            api_token="tok-123",
            client_id="client",
            client_secret="shhh",
        ),
    )


class TestQualtricsSource:
    def setup_method(self) -> None:
        self.source = source_module.QualtricsSource()

    def test_only_responses_sync_incrementally(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(_config(), team_id=1)}

        responses = schemas["survey_responses"]
        assert responses.supports_incremental is True
        # Exported responses can be restated under the same id, so append would duplicate them.
        assert responses.supports_append is False
        assert [field["field"] for field in responses.incremental_fields] == ["recordedDate"]
        assert all(not schemas[name].supports_incremental for name in EXPECTED_ENDPOINTS - {"survey_responses"})

    def test_api_version_is_pinned_to_the_path_the_code_calls(self) -> None:
        assert self.source.supported_versions == ("v3",)
        assert self.source.default_version == "v3"
        assert self.source.resolve_api_version(None) == "v3"

    @pytest.mark.parametrize(
        "selection, expected",
        [
            ("api_token", QualtricsCredentials(method="api_token", api_token="tok-123")),
            (
                "oauth_client_credentials",
                QualtricsCredentials(method="oauth_client_credentials", client_id="client", client_secret="shhh"),
            ),
        ],
    )
    def test_credentials_are_read_from_the_selected_auth_method(
        self, selection: str, expected: QualtricsCredentials
    ) -> None:
        assert source_module._credentials_from_config(_config(selection)) == expected
