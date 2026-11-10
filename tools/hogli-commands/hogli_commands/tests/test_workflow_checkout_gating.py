from pathlib import Path

import pytest

import yaml
from hogli_commands.workflow_lint.checks.checkout_work_gate import CheckoutWorkGateCheck
from hogli_commands.workflow_lint.model import read_workflows


@pytest.mark.parametrize(
    ("checkout", "work", "job_options", "expected"),
    [
        pytest.param(
            {}, [{"run": "check", "if": "needs.changes.outputs.files == 'true'"}], {}, True, id="idle-checkout"
        ),
        pytest.param(
            {},
            [
                {"uses": "example/check@v1", "if": "needs.changes.outputs.files == 'true'"},
                {"run": "check", "if": "${{ needs.changes.outputs.files=='true' }}"},
            ],
            {},
            True,
            id="shared-gate",
        ),
        pytest.param(
            {"if": "needs.changes.outputs.files == 'true'"},
            [{"run": "check", "if": "needs.changes.outputs.files == 'true'"}],
            {},
            False,
            id="gated-checkout",
        ),
        pytest.param({}, [{"run": "check"}], {}, False, id="unconditional-work"),
        pytest.param({}, [], {}, False, id="checkout-only"),
        pytest.param(
            {},
            [{"run": "setup"}, {"run": "check", "if": "needs.changes.outputs.files == 'true'"}],
            {},
            False,
            id="unconditional-setup",
        ),
        pytest.param(
            {},
            [
                {"run": "check", "if": "needs.changes.outputs.files == 'true'"},
                {"run": "check-other", "if": "needs.changes.outputs.other == 'true'"},
            ],
            {},
            False,
            id="different-gates",
        ),
        pytest.param(
            {},
            [{"run": "check", "if": "steps.changes.outputs.files == 'true'"}],
            {},
            False,
            id="checkout-dependent-gate",
        ),
        pytest.param(
            {"id": "checkout"},
            [{"run": "check", "if": "needs.changes.outputs.files == 'true'"}],
            {"outputs": {"sha": "${{ steps.checkout.outputs.commit }}"}},
            False,
            id="checkout-output",
        ),
        pytest.param(
            {},
            [{"run": "check", "if": "needs.changes.outputs.files == 'true'"}],
            {"if": "${{ needs.changes.outputs.files=='true' }}"},
            False,
            id="job-already-gated",
        ),
        pytest.param(
            {},
            [{"run": "check", "if": "needs.changes.outputs.files == 'true'"}],
            {"if": "needs.changes.outputs.files == 'true' && github.event_name == 'pull_request'"},
            False,
            id="stronger-job-gate",
        ),
        pytest.param(
            {},
            [{"run": "check", "if": "needs.changes.outputs.files == 'true' && hashFiles('input') != ''"}],
            {},
            False,
            id="checkout-dependent-expression",
        ),
    ],
)
def test_checkout_work_gate(
    tmp_path: Path,
    checkout: dict[str, object],
    work: list[dict[str, object]],
    job_options: dict[str, object],
    expected: bool,
) -> None:
    workflow = {
        "name": "Checks",
        "on": ["pull_request"],
        "jobs": {
            "lint": {
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 5,
                "steps": [{"uses": "actions/checkout@v6", **checkout}, *work],
                **job_options,
            }
        },
    }
    (tmp_path / "checks.yml").write_text(yaml.safe_dump(workflow))

    result = CheckoutWorkGateCheck().run(list(read_workflows(tmp_path)))

    assert len(result.issues) == int(expected)
    if expected:
        issue = result.issues[0]
        assert issue.workflow == "checks.yml"
        assert issue.job == "lint"
        assert issue.step == "step[0]"
        assert "needs.changes.outputs.files" in issue.message
