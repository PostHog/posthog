import pytest

from products.wizard.backend.logic.workers.wizard_error_output import WizardErrorLine, stderr_to_wizard_error


@pytest.mark.parametrize(
    ("stderr", "expected"),
    (
        (
            'Wizard output\nphw-error: {"code":"PHW_DETECT_NO_POSTHOG_SDK","message":"Missing SDK"}',
            WizardErrorLine(code="PHW_DETECT_NO_POSTHOG_SDK", message="Missing SDK"),
        ),
        (
            'phw-error: {"code":"PHW_DETECT_NO_FRAMEWORK"}\nphw-error: {"code":"PHW_AGENT_NO_PROGRESS"}',
            WizardErrorLine(code="PHW_AGENT_NO_PROGRESS", message=None),
        ),
        (
            'phw-error: {"code":"PHW_AGENT_API_ERROR","message":' + '"' + "x" * 600 + '"}',
            WizardErrorLine(code="PHW_AGENT_API_ERROR", message="x" * 500),
        ),
        (
            'phw-error: {"code":"PHW_FUTURE_ERROR","message":{"nested":true}}',
            WizardErrorLine(code="PHW_FUTURE_ERROR", message=None),
        ),
        ('phw-error: {"code":"detect_no_framework"}', None),
        ('phw-error: {"message":"Missing code"}', None),
        ("phw-error: not-json", None),
        ("ordinary stderr", None),
    ),
)
def test_stderr_to_wizard_error(stderr: str, expected: WizardErrorLine | None) -> None:
    assert stderr_to_wizard_error(stderr) == expected
