import pytest
from unittest.mock import patch

from stripe_mock.config import ErrorConfig


class TestHealthEndpoint:
    def test_returns_ok(self, client):
        resp = client.get("/_health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "collections" in data


class TestListEndpoints:
    @pytest.mark.parametrize(
        "resource,collection",
        [
            ("accounts", "accounts"),
            ("balance_transactions", "balance_transactions"),
            ("charges", "charges"),
            ("disputes", "disputes"),
            ("invoiceitems", "invoice_items"),
            ("payouts", "payouts"),
            ("prices", "prices"),
            ("products", "products"),
            ("refunds", "refunds"),
            ("credit_notes", "credit_notes"),
        ],
    )
    def test_list_returns_list_object(self, client, resource, collection):
        resp = client.get(f"/v1/{resource}?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert isinstance(data["data"], list)
        assert "has_more" in data
        assert data["url"] == f"/v1/{resource}"

    def test_list_pagination(self, client):
        resp1 = client.get("/v1/charges?limit=2")
        data1 = resp1.json()
        assert len(data1["data"]) == 2
        assert data1["has_more"] is True

        last_id = data1["data"][-1]["id"]
        resp2 = client.get(f"/v1/charges?limit=2&starting_after={last_id}")
        data2 = resp2.json()
        assert data2["data"][0]["id"] != data1["data"][0]["id"]

    def test_list_unknown_resource(self, client):
        resp = client.get("/v1/nonexistent")
        data = resp.json()
        assert "error" in data

    def test_list_with_created_gt_filter(self, client):
        all_resp = client.get("/v1/charges?limit=100")
        all_charges = all_resp.json()["data"]
        if len(all_charges) < 2:
            pytest.skip("Not enough charges")

        midpoint_ts = all_charges[len(all_charges) // 2]["created"]
        filtered_resp = client.get(f"/v1/charges?limit=100&created[gt]={midpoint_ts}")
        filtered = filtered_resp.json()["data"]
        assert all(c["created"] > midpoint_ts for c in filtered)


class TestSearchEndpoints:
    @pytest.mark.parametrize("resource", ["customers", "subscriptions", "invoices"])
    def test_search_returns_search_result_object(self, client, resource):
        resp = client.get(f"/v1/{resource}/search?query=created>0&limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "search_result"
        assert isinstance(data["data"], list)
        assert "has_more" in data
        assert "total_count" in data
        assert data["url"] == f"/v1/{resource}/search"

    def test_search_pagination_via_page_token(self, client):
        resp1 = client.get("/v1/customers/search?query=created>0&limit=2")
        data1 = resp1.json()
        assert data1["has_more"] is True
        assert "next_page" in data1

        resp2 = client.get(f"/v1/customers/search?query=created>0&limit=2&page={data1['next_page']}")
        data2 = resp2.json()
        assert data2["data"][0]["id"] != data1["data"][0]["id"]

    def test_search_unsupported_resource(self, client):
        resp = client.get("/v1/charges/search?query=created>0")
        data = resp.json()
        assert "error" in data


class TestNestedEndpoints:
    def test_customer_balance_transactions(self, client):
        customers = client.get("/v1/customers/search?query=created>0&limit=1").json()["data"]
        cust_id = customers[0]["id"]
        resp = client.get(f"/v1/customers/{cust_id}/balance_transactions?limit=10")
        data = resp.json()
        assert data["object"] == "list"
        assert data["url"] == f"/v1/customers/{cust_id}/balance_transactions"

    def test_customer_payment_methods(self, client):
        customers = client.get("/v1/customers/search?query=created>0&limit=1").json()["data"]
        cust_id = customers[0]["id"]
        resp = client.get(f"/v1/customers/{cust_id}/payment_methods?limit=10")
        data = resp.json()
        assert data["object"] == "list"
        assert len(data["data"]) >= 1
        assert data["data"][0]["customer"] == cust_id

    def test_invoice_lines(self, client):
        invoices = client.get("/v1/invoices/search?query=created>0&limit=1").json()["data"]
        if not invoices:
            pytest.skip("No invoices")
        inv_id = invoices[0]["id"]
        resp = client.get(f"/v1/invoices/{inv_id}/lines?limit=10")
        data = resp.json()
        assert data["object"] == "list"
        assert data["url"] == f"/v1/invoices/{inv_id}/lines"

    def test_nonexistent_customer_returns_empty(self, client):
        resp = client.get("/v1/customers/cus_nonexistent/payment_methods?limit=10")
        data = resp.json()
        assert data["data"] == []
        assert data["has_more"] is False


class TestWebhookEndpoints:
    def test_create_and_list_webhook(self, client):
        create_resp = client.post(
            "/v1/webhook_endpoints", data={"url": "https://example.com/hook", "description": "test"}
        )
        assert create_resp.status_code == 200
        wh = create_resp.json()
        assert wh["object"] == "webhook_endpoint"
        assert wh["url"] == "https://example.com/hook"
        assert "secret" in wh

        list_resp = client.get("/v1/webhook_endpoints")
        assert any(w["id"] == wh["id"] for w in list_resp.json()["data"])

    def test_delete_webhook(self, client):
        create_resp = client.post("/v1/webhook_endpoints", data={"url": "https://example.com/hook2"})
        wh_id = create_resp.json()["id"]

        del_resp = client.delete(f"/v1/webhook_endpoints/{wh_id}")
        assert del_resp.json()["deleted"] is True

        list_resp = client.get("/v1/webhook_endpoints")
        assert not any(w["id"] == wh_id for w in list_resp.json()["data"])


class TestErrorInjection:
    def test_error_injection_returns_configured_status(self, client):
        errors = {"/v1/charges": ErrorConfig(status=500, message="Boom", rate=1.0)}
        with patch("stripe_mock.main.mock_config") as cfg:
            cfg.errors = errors
            resp = client.get("/v1/charges?limit=1")
            assert resp.status_code == 500
            assert resp.json()["error"]["message"] == "Boom"

    def test_error_injection_does_not_affect_other_routes(self, client):
        errors = {"/v1/charges": ErrorConfig(status=500, message="Boom", rate=1.0)}
        with patch("stripe_mock.main.mock_config") as cfg:
            cfg.errors = errors
            resp = client.get("/v1/products?limit=1")
            assert resp.status_code == 200

    def test_zero_rate_never_triggers(self, client):
        errors = {"/v1/charges": ErrorConfig(status=500, message="Boom", rate=0.0)}
        with patch("stripe_mock.main.mock_config") as cfg:
            cfg.errors = errors
            for _ in range(10):
                resp = client.get("/v1/charges?limit=1")
                assert resp.status_code == 200
