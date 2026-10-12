import pytest

from requests_mock import Mocker

from sources.sdk import ResumableSourceManager, SourceInputs, UnknownResourceError
from sources.sim._config import SimSourceConfig
from sources.sim.sim import SimResumeConfig
from sources.sim.source import SimSource


def test_unknown_schema_rejected_before_network(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    http: Mocker,
) -> None:
    source = SimSource()
    valid, message = source.validate_credentials(config, 1, schema_name="unknown")
    assert not valid
    assert message == "Unknown Sim table: unknown. Select workflows or logs."
    inputs.schema_name = "unknown"
    with pytest.raises(UnknownResourceError, match="unknown"):
        source.source_for_pipeline(config, manager, inputs)
    assert http.call_count == 0
