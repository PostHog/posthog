from types import SimpleNamespace
from typing import Any

from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.settings import (
    ENDPOINT_NAME,
    NO_DIMENSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.source import (
    MicrosoftClaritySource,
)


def _config(
    api_token: str = "token",
    num_of_days: str = "1",
    dimension1: str | None = NO_DIMENSION,
    dimension2: str | None = NO_DIMENSION,
    dimension3: str | None = NO_DIMENSION,
) -> Any:
    return SimpleNamespace(
        api_token=api_token,
        num_of_days=num_of_days,
        dimension1=dimension1,
        dimension2=dimension2,
        dimension3=dimension3,
    )


class TestSourceForPipeline:
    def test_plumbs_config_into_transport(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        sentinel = object()

        def fake_source(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(source_module, "microsoft_clarity_source", fake_source)

        inputs = SimpleNamespace(schema_name=ENDPOINT_NAME, team_id=1, job_id="job", logger=MagicMock())
        result = MicrosoftClaritySource().source_for_pipeline(
            _config(
                api_token="tok", num_of_days="3", dimension1="OS", dimension2=NO_DIMENSION, dimension3=NO_DIMENSION
            ),
            inputs,  # type: ignore[arg-type]
        )

        assert result is sentinel
        assert captured == {
            "token": "tok",
            "num_of_days": "3",
            "dimension1": "OS",
            "dimension2": NO_DIMENSION,
            "dimension3": NO_DIMENSION,
        }
