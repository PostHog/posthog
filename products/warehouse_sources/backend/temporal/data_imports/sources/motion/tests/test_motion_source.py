from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.motion import MotionSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.motion.source import MotionSource

_SOURCE = "products.warehouse_sources.backend.temporal.data_imports.sources.motion.source"


class TestMotionSourceClass:
    def test_the_job_context_reaches_the_transport(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "tasks"
        inputs.team_id = 7
        inputs.job_id = "job-1"

        with mock.patch(f"{_SOURCE}.motion_source") as motion_source:
            MotionSource().source_for_pipeline(MotionSourceConfig(api_key="key"), mock.MagicMock(), inputs)

        assert motion_source.call_args.kwargs["team_id"] == 7
        assert motion_source.call_args.kwargs["job_id"] == "job-1"
