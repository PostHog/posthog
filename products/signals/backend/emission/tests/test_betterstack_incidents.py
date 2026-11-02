import pytest

from products.signals.backend.emission.betterstack_incidents import betterstack_emitter, redact_monitored_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        ("https://api.example.com/health", "https://api.example.com/health"),
        ("https://user:secret@api.example.com:8443/health?token=abc#frag", "https://api.example.com:8443/health"),
        ("http://[::1]:8080/ping?key=x", "http://[::1]:8080/ping"),
        ("https://api.example.com:notaport/health", None),
    ],
)
def test_redact_monitored_url(raw, expected):
    assert redact_monitored_url(raw) == expected


def test_emitter_redacts_url_credentials():
    output = betterstack_emitter(
        1,
        {
            "id": "42",
            "name": "API health",
            "cause": "Status 500",
            "url": "https://user:secret@api.example.com/health?token=abc",
            "started_at": "2026-01-01T00:00:00Z",
        },
    )
    assert output is not None
    assert output.extra == {"url": "https://api.example.com/health", "started_at": "2026-01-01T00:00:00Z"}
    assert "secret" not in output.description
