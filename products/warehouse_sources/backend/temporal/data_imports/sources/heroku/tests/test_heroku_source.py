from unittest.mock import MagicMock, patch

import requests

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.heroku import HerokuResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.source import HerokuSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.heroku.source"


def _source_inputs(schema_name: str = "apps") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestHerokuSource:
    def setup_method(self) -> None:
        self.source = HerokuSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.HEROKU

    def test_source_config_requires_api_key_as_secret(self) -> None:
        config = self.source.get_source_config
        api_key_fields = [f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key"]
        assert len(api_key_fields) == 1
        assert api_key_fields[0].secret
        assert api_key_fields[0].required
        assert api_key_fields[0].type == "password"

    def test_docs_url_matches_heroku_slug(self) -> None:
        assert self.source.get_source_config.docsUrl == "https://posthog.com/docs/cdp/sources/heroku"

    def test_get_schemas_returns_full_refresh_only_endpoints(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Heroku has no server-side timestamp filters; flipping any of these on without one
        # would sync incorrect incremental data.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["apps", "releases"])
        assert {s.name for s in schemas} == {"apps", "releases"}

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)

    def test_validate_credentials_maps_probe_result(self) -> None:
        config = MagicMock()
        config.api_key = "key"

        with patch(f"{SOURCE_PATH}.validate_heroku_credentials", return_value=True) as probe:
            assert self.source.validate_credentials(config, team_id=1) == (True, None)
        probe.assert_called_once_with("key")

        with patch(f"{SOURCE_PATH}.validate_heroku_credentials", return_value=False):
            valid, message = self.source.validate_credentials(config, team_id=1)
        assert not valid
        assert message == "Invalid Heroku API key"

    def test_resumable_source_manager_bound_to_heroku_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs())
        assert manager._data_class is HerokuResumeConfig

    def test_source_for_pipeline_plumbs_config_and_schema(self) -> None:
        config = MagicMock()
        config.api_key = "key"
        inputs = _source_inputs(schema_name="releases")
        manager = MagicMock()

        with patch(f"{SOURCE_PATH}.heroku_source") as mocked_source:
            response = self.source.source_for_pipeline(config, manager, inputs)

        assert response is mocked_source.return_value
        mocked_source.assert_called_once_with(
            api_key="key",
            endpoint="releases",
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=manager,
        )

    def test_non_retryable_error_keys_match_requests_error_strings(self) -> None:
        # `get_non_retryable_errors` keys are matched as substrings of the raised error; if
        # the key format drifts from what requests actually produces, credential failures
        # retry forever instead of disabling the source.
        response = requests.Response()
        response.status_code = 401
        response.reason = "Unauthorized"  # verified live: Heroku sends this phrase over HTTP/1.1
        response.url = "https://api.heroku.com/apps/some-app/releases"
        try:
            response.raise_for_status()
            raise AssertionError("raise_for_status did not raise")
        except requests.HTTPError as e:
            error_string = str(e)

        assert any(key in error_string for key in self.source.get_non_retryable_errors())
