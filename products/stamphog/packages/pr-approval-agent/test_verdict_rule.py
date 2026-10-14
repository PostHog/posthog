import pytest

from verdict_rule import ReviewFacts, derive_verdict


def _facts(**overrides: object) -> ReviewFacts:
    output: dict[str, object] = {
        "risky_areas": [],
        "reviews_on_current_head": [],
        "owning_team_author": False,
        "strong_familiarity": False,
        "unresolved_substantive_concerns": [],
        "other_refusal_grounds": [],
        **overrides,
    }
    return ReviewFacts.from_output(output)


_RISKY = ["billing: ee/billing/quota.py changes how the quota limit is computed"]


@pytest.mark.parametrize(
    "overrides, verdict, risk, issues",
    [
        pytest.param({}, "APPROVE", "low", (), id="clean"),
        pytest.param(
            {"other_refusal_grounds": ["Maintainer hold by @alice"], "owning_team_author": True},
            "REFUSE",
            "low",
            ("Maintainer hold by @alice",),
            id="refusal-ground-beats-assurance",
        ),
        pytest.param(
            {"unresolved_substantive_concerns": ["@bob on api.py: drops team_id filter"], "risky_areas": _RISKY},
            "REFUSE",
            "high",
            ("@bob on api.py: drops team_id filter",),
            id="concern-in-risky-territory",
        ),
        pytest.param(
            {"risky_areas": _RISKY},
            "ESCALATE",
            "high",
            ("Risky territory without independent assurance: " + _RISKY[0],),
            id="risky-unassured",
        ),
        pytest.param(
            {"risky_areas": _RISKY, "reviews_on_current_head": ["@carol APPROVED"]},
            "APPROVE",
            "medium",
            (),
            id="risky-assured-by-review",
        ),
        pytest.param(
            {"risky_areas": _RISKY, "owning_team_author": True}, "APPROVE", "medium", (), id="risky-owning-team"
        ),
        pytest.param({"risky_areas": _RISKY, "strong_familiarity": True}, "APPROVE", "medium", (), id="risky-strong"),
        pytest.param({"other_refusal_grounds": ["  "], "risky_areas": [""]}, "APPROVE", "low", (), id="blank-entries"),
        pytest.param(
            {"risky_areas": _RISKY, "shape_waives_assurance": True},
            "APPROVE",
            "medium",
            (),
            id="risky-approvable-shape",
        ),
        pytest.param(
            {"other_refusal_grounds": ["Maintainer hold by @alice"], "shape_waives_assurance": True},
            "REFUSE",
            "low",
            ("Maintainer hold by @alice",),
            id="refusal-ground-beats-approvable-shape",
        ),
    ],
)
def test_derive_verdict(overrides: dict, verdict: str, risk: str, issues: tuple[str, ...]) -> None:
    facts = _facts(**{name: value for name, value in overrides.items() if name != "shape_waives_assurance"})
    ruled = derive_verdict(facts, shape_waives_assurance=overrides.get("shape_waives_assurance", False))
    assert (ruled.verdict, ruled.risk, ruled.issues) == (verdict, risk, issues)
