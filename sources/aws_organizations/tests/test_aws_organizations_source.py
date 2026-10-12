from collections.abc import Iterable
from typing import Any, cast

from unittest import mock

import structlog

from sources.aws_organizations import (
    aws_organizations as transport_module,
    source as source_module,
)
from sources.aws_organizations._config import AwsOrganizationsSourceConfig
from sources.aws_organizations.settings import ORGANIZATIONS_API_VERSION
from sources.aws_organizations.source import AwsOrganizationsSource
from sources.sdk import SourceInputs


def make_inputs(schema_name: str) -> SourceInputs:
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
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestAwsOrganizationsSource:
    def setup_method(self) -> None:
        self.source = AwsOrganizationsSource()
        self.config = AwsOrganizationsSourceConfig(
            aws_access_key_id="AKIAEXAMPLE",
            aws_secret_access_key="secret",
            aws_session_token=None,
        )

    def test_source_for_pipeline_passes_the_credentials_and_resolved_version_to_the_transport(self) -> None:
        inputs = make_inputs("accounts")
        manager = self.source.get_resumable_source_manager(inputs)

        with mock.patch.object(transport_module, "get_rows", return_value=iter([])) as get_rows:
            response = self.source.source_for_pipeline(self.config, manager, inputs)
            cast(Iterable[Any], response.items())

        assert get_rows.call_args.kwargs["aws_access_key_id"] == "AKIAEXAMPLE"
        assert get_rows.call_args.kwargs["aws_secret_access_key"] == "secret"
        assert get_rows.call_args.kwargs["endpoint"] == "accounts"
        assert get_rows.call_args.kwargs["api_version"] == ORGANIZATIONS_API_VERSION

    def test_endpoint_permissions_are_probed_per_table(self) -> None:
        with mock.patch.object(source_module, "probe_endpoint_permissions", return_value={"accounts": None}) as probe:
            assert self.source.get_endpoint_permissions(self.config, team_id=1, endpoints=["accounts"]) == {
                "accounts": None
            }

        assert probe.call_args.args == ("AKIAEXAMPLE", "secret", None, ["accounts"])
        assert probe.call_args.kwargs == {"api_version": ORGANIZATIONS_API_VERSION}
