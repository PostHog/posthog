from decimal import Decimal

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import httpx
from parameterized import parameterized

from products.notebooks.backend.widget_generation_cost import get_widget_generation_cost


@override_settings(AI_GATEWAY_URL="http://gateway.test/v1", AI_GATEWAY_API_KEY="test-gateway-key")
class TestWidgetGenerationCost(SimpleTestCase):
    def test_sums_generation_retries_and_review_with_billing_markup(self) -> None:
        responses = [
            httpx.Response(200, json={"cost_usd": cost}, request=httpx.Request("GET", "http://gateway.test"))
            for cost in ("0.04", "0.01", "0.002")
        ]
        with patch.object(httpx.Client, "get", side_effect=responses) as get:
            cost = get_widget_generation_cost(["generation", "retry", "review"])

        assert cost == Decimal("0.062400")
        assert [call.args[0] for call in get.call_args_list] == [
            "usage/generation",
            "usage/retry",
            "usage/review",
        ]

    @parameterized.expand([(None,), ("not-a-cost",), ("NaN",), ("Infinity",), ("-1",)])
    def test_invalid_cost_is_unavailable(self, amount: str | None) -> None:
        response = httpx.Response(200, json={"cost_usd": amount}, request=httpx.Request("GET", "http://gateway.test"))
        with patch.object(httpx.Client, "get", return_value=response):
            assert get_widget_generation_cost(["generation"]) is None

    def test_missing_request_ids_do_not_report_a_partial_total(self) -> None:
        with patch.object(httpx.Client, "get") as get:
            assert get_widget_generation_cost(["generation", None]) is None
            assert get_widget_generation_cost([]) is None
        get.assert_not_called()

    @parameterized.expand([(404,), (503,)])
    def test_missing_usage_does_not_fail_widget_generation(self, status: int) -> None:
        response = httpx.Response(status, request=httpx.Request("GET", "http://gateway.test"))
        with patch.object(httpx.Client, "get", return_value=response):
            assert get_widget_generation_cost(["generation"]) is None

    @override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY="")
    def test_legacy_gateway_cost_is_unavailable(self) -> None:
        with patch.object(httpx.Client, "get") as get:
            assert get_widget_generation_cost(["generation"]) is None
        get.assert_not_called()
