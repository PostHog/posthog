import pytest

from products.wizard.backend.logic.workers.wizard_error_output import stderr_to_wizard_error_code


@pytest.mark.parametrize(
    ("stderr", "expected"),
    (
        (
            'Wizard output\nphw-error: {"code":"PHW_DETECT_NO_POSTHOG_SDK","message":"Missing SDK"}',
            "PHW_DETECT_NO_POSTHOG_SDK",
        ),
        (
            'phw-error: {"code":"PHW_DETECT_NO_FRAMEWORK"}\nphw-error: {"code":"PHW_AGENT_NO_PROGRESS"}',
            "PHW_AGENT_NO_PROGRESS",
        ),
        ('phw-error: {"code":"PHW_FUTURE_ERROR"}', "PHW_FUTURE_ERROR"),
        ('phw-error: {"code":"detect_no_framework"}', None),
        ('phw-error: {"message":"Missing code"}', None),
        ("phw-error: not-json", None),
        ("ordinary stderr", None),
    ),
)
def test_stderr_to_wizard_error_code(stderr: str, expected: str | None) -> None:
    assert stderr_to_wizard_error_code(stderr) == expected
