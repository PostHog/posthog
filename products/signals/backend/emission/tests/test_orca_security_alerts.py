import pytest

from products.signals.backend.emission.orca_security_alerts import orca_security_alert_emitter

FULL = {
    "id": "orca-alert-1",
    "alert_type": "S3 bucket is publicly readable",
    "category": "Data at risk",
    "risk_level": "high",
    "orca_score": 7.5,
    "status": "open",
    "source": "orca",
    "created_at": "2026-01-01T00:00:00Z",
}


def test_full_record():
    output = orca_security_alert_emitter(1, FULL)
    assert output is not None
    assert output.source_id == "orca-alert-1"
    assert output.description == "S3 bucket is publicly readable (Data at risk) on orca"
    assert output.extra == {
        "category": "Data at risk",
        "risk_level": "high",
        "orca_score": "7.5",
        "status": "open",
        "source": "orca",
        "created_at": "2026-01-01T00:00:00Z",
    }


@pytest.mark.parametrize(
    "overrides,expected_title",
    [
        ({"category": None}, "S3 bucket is publicly readable on orca"),
        ({"source": ""}, "S3 bucket is publicly readable (Data at risk)"),
        ({"category": None, "source": None}, "S3 bucket is publicly readable"),
    ],
)
def test_title_composition(overrides, expected_title):
    output = orca_security_alert_emitter(1, {**FULL, **overrides})
    assert output is not None
    assert output.description == expected_title


@pytest.mark.parametrize("overrides", [{"alert_type": None}, {"alert_type": ""}, {"id": None}])
def test_returns_none_without_id_or_alert_type(overrides):
    assert orca_security_alert_emitter(1, {**FULL, **overrides}) is None
