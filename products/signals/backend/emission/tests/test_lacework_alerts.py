import pytest

from products.signals.backend.emission.lacework_alerts import lacework_alert_emitter

FULL = {
    "alert_id": 1234,
    "alert_name": "Service called GCP API",
    "alert_type": "CloudActivityLogIngestion",
    "alert_subject": "Unusual API call",
    "alert_description": "A service account called an API it never used before",
    "severity": "High",
    "status": "Open",
    "start_time": "2026-01-01T00:00:00Z",
    "internet_exposure": "1",
}


def test_full_record():
    output = lacework_alert_emitter(1, FULL)
    assert output is not None
    assert output.source_id == "1234"
    assert output.description == (
        "Service called GCP API\nUnusual API call\nA service account called an API it never used before"
    )
    assert output.extra == {
        "alert_type": "CloudActivityLogIngestion",
        "severity": "High",
        "status": "Open",
        "internet_exposure": "1",
        "start_time": "2026-01-01T00:00:00Z",
    }


@pytest.mark.parametrize(
    "overrides,expected_description",
    [
        (
            {"alert_name": None},
            "CloudActivityLogIngestion\nUnusual API call\nA service account called an API it never used before",
        ),
        ({"alert_subject": "", "alert_description": None}, "Service called GCP API"),
        ({"alert_subject": "Same", "alert_description": "Same"}, "Service called GCP API\nSame"),
    ],
)
def test_text_fallbacks(overrides, expected_description):
    output = lacework_alert_emitter(1, {**FULL, **overrides})
    assert output is not None
    assert output.description == expected_description


@pytest.mark.parametrize(
    "overrides",
    [{"alert_name": None, "alert_type": None}, {"alert_name": "", "alert_type": ""}, {"alert_id": None}],
)
def test_returns_none_without_id_or_title(overrides):
    assert lacework_alert_emitter(1, {**FULL, **overrides}) is None


def test_missing_id_column_raises():
    record = {k: v for k, v in FULL.items() if k != "alert_id"}
    with pytest.raises(ValueError):
        lacework_alert_emitter(1, record)
