from posthog.test.base import BaseTest
from unittest.mock import PropertyMock, patch

from django.test import override_settings

from langchain_core.runnables import RunnableLambda

from products.posthog_ai.backend.chart_spec.generator import (
    ChartSpecGenerator,
    ChartSpecGeneratorOutput,
    generate_chart_spec_schema,
)
from products.posthog_ai.backend.chart_spec.schema import ChartSpec

COMBO_SPEC = ChartSpec(
    chartType="combo",
    title="Revenue vs conversion rate",
    narrative="Revenue grows on volume while conversion holds steady.",
    labels=["Mon", "Tue", "Wed"],
    axes=[
        {"id": "left", "format": "currency", "currency": "USD"},
        {"id": "right", "format": "percentage"},
    ],
    series=[
        {"key": "revenue", "label": "Revenue", "type": "bar", "axis": "left", "data": [4200, 5100, 4800]},
        {"key": "cvr", "label": "Conversion", "type": "line", "axis": "right", "data": [3.1, 3.3, 3.0]},
    ],
    referenceLines=[{"value": 5000, "variant": "goal", "axis": "left", "label": "Target"}],
)


@override_settings(IN_UNIT_TESTING=True)
class TestChartSpecGenerator(BaseTest):
    async def test_agenerate_parses_structured_output_into_chart_spec(self):
        generator = ChartSpecGenerator(self.team, self.user)
        with patch.object(ChartSpecGenerator, "_model", new_callable=PropertyMock) as model_mock:
            model_mock.return_value = RunnableLambda(lambda _: {"chart": COMBO_SPEC.model_dump()})
            result = await generator.agenerate(
                data_summary="columns: day, revenue, conversion_rate",
                instruction="show revenue against conversion rate",
            )
        assert isinstance(result, ChartSpec)
        assert result.chartType == "combo"
        assert [s.axis for s in result.series] == ["left", "right"]
        assert result.referenceLines is not None and result.referenceLines[0].value == 5000

    def test_output_wrapper_validates_a_well_formed_spec(self):
        wrapped = ChartSpecGeneratorOutput.model_validate({"chart": COMBO_SPEC.model_dump()})
        assert wrapped.chart.chartType == "combo"

    def test_generated_schema_is_dereferenced_and_wraps_chart(self):
        schema = generate_chart_spec_schema()
        params = schema["parameters"]
        assert params["required"] == ["chart"]
        assert "chart" in params["properties"]
        # `$defs`/`$ref` must be inlined so the model sees a self-contained schema.
        assert "$defs" not in params["properties"]["chart"]
        assert "$ref" not in str(params["properties"]["chart"].get("properties", {}).get("series", {}))
