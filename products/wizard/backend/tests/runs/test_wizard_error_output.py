import json

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
        *(
            (
                'phw-error: {"code":"PHW_AGENT_API_ERROR","message":' + json.dumps(message) + "}",
                WizardErrorLine(code="PHW_AGENT_API_ERROR", message=expected_message),
            )
            for message, expected_message in (
                ("Gateway refused pha_FakeOAuthToken1234 for team 2", "Gateway refused [REDACTED] for team 2"),
                ("clone failed: gho_FAKEFAKEFAKEFAKEFAKE1234", "clone failed: [REDACTED]"),
                (
                    "fetch https://x-access-token:fake-secret@github.com/org/repo.git failed",
                    "fetch https://[REDACTED]@github.com/org/repo.git failed",
                ),
                ("401 with Authorization: Bearer fake.jwt.value-1234", "401 with Authorization: Bearer [REDACTED]"),
                ('config {"apiKey": "fake-key-value"} rejected', 'config {"apiKey": "[REDACTED]"} rejected'),
                ("refresh failed: access_token=fake-access-value", "refresh failed: access_token=[REDACTED]"),
                ("x" * 490 + " pha_FakeOAuthToken1234", "x" * 490 + " [REDACTED"),
                (
                    "OpenAI API error (400): 400 invalid request body",
                    "OpenAI API error (400): 400 invalid request body",
                ),
                ("Headless mode requires --api-key (phx_xxx)", "Headless mode requires --api-key (phx_xxx)"),
            )
        ),
        ('phw-error: {"code":"detect_no_framework"}', None),
        ('phw-error: {"message":"Missing code"}', None),
        ("phw-error: not-json", None),
        ("ordinary stderr", None),
    ),
)
def test_stderr_to_wizard_error(stderr: str, expected: WizardErrorLine | None) -> None:
    assert stderr_to_wizard_error(stderr) == expected
