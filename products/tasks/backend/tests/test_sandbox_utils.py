import pytest

from django.test import override_settings

from products.tasks.backend.temporal.process_task.utils import get_sandbox_api_url


@pytest.mark.parametrize(
    "sandbox_api_url, expected",
    [
        ("https://xxx.ngrok.dev", "https://xxx.ngrok.dev"),
        (None, "http://localhost:8010"),
    ],
    ids=["uses_sandbox_api_url_when_set", "falls_back_to_site_url_when_none"],
)
def test_get_sandbox_api_url(sandbox_api_url: str | None, expected: str) -> None:
    with override_settings(SANDBOX_API_URL=sandbox_api_url, SITE_URL="http://localhost:8010"):
        assert get_sandbox_api_url() == expected
