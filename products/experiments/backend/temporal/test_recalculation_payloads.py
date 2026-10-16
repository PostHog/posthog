from typing import Any

import pytest

import temporalio.converter
from temporalio.contrib.pydantic import pydantic_data_converter

from products.experiments.backend.temporal.models import ExperimentMetricToRecalculate, MetricOutOfTimeFailure

CONVERTERS = {
    "default": temporalio.converter.default().payload_converter,
    "pydantic": pydantic_data_converter.payload_converter,
}

PAYLOADS_WITHOUT_ROLE: list[tuple[type, dict[str, Any]]] = [
    (ExperimentMetricToRecalculate, {"experiment_id": 1, "metric_uuid": "m1", "metric_type": "secondary"}),
    (
        MetricOutOfTimeFailure,
        {"recalculation_id": "r1", "experiment_id": 1, "metric_uuid": "m1", "metric_type": "secondary"},
    ),
]


@pytest.mark.parametrize("converter_name", CONVERTERS)
@pytest.mark.parametrize("payload_class,fields", PAYLOADS_WITHOUT_ROLE)
def test_payload_without_role_decodes_with_role(converter_name: str, payload_class: type, fields: dict) -> None:
    converter = CONVERTERS[converter_name]

    decoded = converter.from_payloads(converter.to_payloads([fields]), [payload_class])[0]

    assert decoded.role == "secondary"


@pytest.mark.parametrize("converter_name", CONVERTERS)
@pytest.mark.parametrize("payload_class,fields", PAYLOADS_WITHOUT_ROLE)
def test_payload_with_role_still_carries_metric_type(converter_name: str, payload_class: type, fields: dict) -> None:
    converter = CONVERTERS[converter_name]
    fields_without_metric_type = {name: value for name, value in fields.items() if name != "metric_type"}
    written = payload_class(**fields_without_metric_type, role="secondary")

    encoded = converter.from_payloads(converter.to_payloads([written]), [dict])[0]

    assert encoded["metric_type"] == "secondary"
    assert encoded["role"] == "secondary"
