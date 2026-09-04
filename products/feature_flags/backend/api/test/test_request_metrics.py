from posthog.test.base import APIBaseTest, ClickhouseTestMixin


class TestFlagRequestMetricsAPI(ClickhouseTestMixin, APIBaseTest):
    def test_returns_the_billing_weights_the_usage_report_bills_on(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/flag_requests/volume/")

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["billing_weights"], {"decide": 1, "local-evaluation": 10, "remote-config": 0})

    def test_rejects_an_unknown_breakdown(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/flag_requests/volume/?breakdown=ip_address")

        self.assertEqual(response.status_code, 400, response.json())
