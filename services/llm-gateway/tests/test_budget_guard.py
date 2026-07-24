from llm_gateway.budget_guard import evaluate_request


def test_override_always_allows() -> None:
    assert evaluate_request(20, 25, override=True).allow is True


def test_no_cap_allows() -> None:
    assert evaluate_request(0, 99).allow is True
    assert evaluate_request(None, 99).allow is True


def test_fail_open_when_spend_unresolved() -> None:
    d = evaluate_request(20, None)
    assert d.allow is True
    assert d.headers["x-posthog-budget"] == "unknown"


def test_exceeded_denies() -> None:
    d = evaluate_request(20, 25)
    assert d.allow is False
    assert d.headers["x-posthog-budget"] == "exceeded"


def test_within_budget_reports_remaining() -> None:
    d = evaluate_request(20, 12)
    assert d.allow is True
    assert d.headers["x-posthog-budget"] == "ok"
    assert d.headers["x-posthog-budget-remaining-usd"] == "8.00"


def test_warns_when_approaching_cap() -> None:
    # 18/20 = 90% > 85% warn threshold
    d = evaluate_request(20, 18)
    assert d.allow is True
    assert d.headers["x-posthog-budget"] == "warn"
    assert d.headers["x-posthog-budget-remaining-usd"] == "2.00"
