import json
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean import (
    DIGITALOCEAN_BASE_URL,
    _paginator,
    digitalocean_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.settings import (
    DIGITALOCEAN_ENDPOINTS,
    PAGE_SIZE,
)

TOP_LEVEL_ENDPOINTS = [name for name, config in DIGITALOCEAN_ENDPOINTS.items() if config.fanout is None]
INVOICE_UUID = "22737513-0ea7-4206-8ceb-98a575af7681"
PROJECT_ID = "4e1bfbc3-dc3e-41f2-a18f-1b4d7ba71679"
DATABASE_UUID = "9cc10173-e9ea-4176-9dbc-a4cee4c4ff30"


def _make_response(json_body: dict[str, Any] | None = None, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(json_body or {}).encode()
    return resp


def _endpoint(resource: Any) -> dict[str, Any]:
    return cast(dict[str, Any], resource["endpoint"])


def _rows(endpoint: str) -> list[dict[str, Any]]:
    resource = digitalocean_source("dop_v1_token", endpoint, team_id=1, job_id="job-1")
    return [row for page in resource for row in page]


class TestDigitalOceanPaginator:
    def test_advances_on_next_page_url(self) -> None:
        # DigitalOcean nests the next-page URL under links.pages.next; a page that has one must
        # continue pagination. A wrong json path (e.g. "links.next") would silently stop after page 1.
        p = _paginator()
        p.update_state(
            _make_response(
                {
                    "droplets": [{"id": 1}],
                    "links": {"pages": {"next": "https://api.digitalocean.com/v2/droplets?page=2"}},
                }
            )
        )

        assert p.has_next_page is True

        req = Request(method="GET", url="https://api.digitalocean.com/v2/droplets")
        p.update_request(req)
        assert req.url == "https://api.digitalocean.com/v2/droplets?page=2"

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(
                {"droplets": [{"id": 1}], "links": {"pages": {"last": "…", "prev": "…"}}}, id="last_page_no_next"
            ),
            pytest.param({"droplets": [{"id": 1}], "links": {}}, id="empty_links"),
            pytest.param({"droplets": []}, id="no_links_key"),
        ],
    )
    def test_stops_when_no_next_page(self, body: dict[str, Any]) -> None:
        p = _paginator()
        p.update_state(_make_response(body))
        assert p.has_next_page is False


class TestDigitalOceanGetResource:
    @pytest.mark.parametrize("endpoint", TOP_LEVEL_ENDPOINTS)
    def test_resource_matches_endpoint_config(self, endpoint: str) -> None:
        config = DIGITALOCEAN_ENDPOINTS[endpoint]
        resource = get_resource(config)
        endpoint_def = _endpoint(resource)

        # data_selector must equal the JSON key DigitalOcean wraps the list under; a mismatch
        # yields an empty table without erroring, so this pins the contract per endpoint.
        assert endpoint_def["data_selector"] == config.data_selector
        assert endpoint_def["path"] == config.path
        assert endpoint_def["params"]["per_page"] == PAGE_SIZE
        # No incremental filter exists on any endpoint, so every table is full replace.
        assert resource["write_disposition"] == "replace"

    def test_images_limits_to_private(self) -> None:
        # Without private=true the images list also returns every public distribution/application
        # image — huge and identical for every account.
        resource = get_resource(DIGITALOCEAN_ENDPOINTS["images"])
        assert _endpoint(resource)["params"]["private"] == "true"


class TestDigitalOceanSensitiveFields:
    _DATABASE_RECORD = {
        "id": "db-1",
        "name": "prod-pg",
        "engine": "pg",
        "region": "nyc1",
        "connection": {"uri": "postgresql://doadmin:secret@host:25060/defaultdb", "password": "secret"},
        "private_connection": {"uri": "postgresql://doadmin:secret@priv-host:25060/defaultdb"},
        "standby_connection": {"password": "secret"},
        "standby_private_connection": {"password": "secret"},
        "users": [{"name": "doadmin", "password": "secret"}],
    }

    def test_databases_strips_credential_bearing_fields(self) -> None:
        # /v2/databases embeds live connection URIs, passwords, and the users list in every
        # record; without stripping they'd land in a queryable warehouse table.
        resource = digitalocean_source("dop_v1_token", "databases", team_id=1, job_id="job-1")
        [transformed] = resource._apply_transforms([dict(self._DATABASE_RECORD)])

        assert transformed == {"id": "db-1", "name": "prod-pg", "engine": "pg", "region": "nyc1"}

    def test_apps_strips_nested_env_and_log_credentials(self) -> None:
        # App specs bury env-var values and log-destination credentials inside spec.services and
        # the deployment spec copy; the strip must recurse to reach them while keeping metadata.
        record = {
            "id": "app-1",
            "spec": {
                "name": "web",
                "services": [
                    {
                        "name": "api",
                        "envs": [{"key": "SECRET_KEY", "value": "leak-me"}],
                        "log_destinations": [{"name": "dd", "datadog": {"api_key": "leak-me"}}],
                    }
                ],
            },
            "active_deployment": {"spec": {"services": [{"name": "api", "envs": [{"value": "leak-me"}]}]}},
        }
        resource = digitalocean_source("dop_v1_token", "apps", team_id=1, job_id="job-1")
        [transformed] = resource._apply_transforms([record])

        assert transformed == {
            "id": "app-1",
            "spec": {"name": "web", "services": [{"name": "api"}]},
            "active_deployment": {"spec": {"services": [{"name": "api"}]}},
        }

    def test_non_sensitive_endpoint_keeps_every_field(self) -> None:
        # Only endpoints that declare sensitive_fields get filtered; everything else must round-trip
        # untouched or the strip would silently drop real data.
        record = {"id": 1, "name": "web-1", "networks": {"v4": [{"ip_address": "1.2.3.4"}]}}
        resource = digitalocean_source("dop_v1_token", "droplets", team_id=1, job_id="job-1")

        assert resource._apply_transforms([dict(record)]) == [record]

    @pytest.mark.parametrize(
        "endpoint,capture_disabled",
        [
            pytest.param("databases", True, id="secrets_in_the_response"),
            pytest.param("invoice_summaries", True, id="billing_identity_in_the_response"),
            pytest.param("invoice_items", True, id="resource_level_spend_in_the_response"),
            pytest.param("database_backups", True, id="secrets_in_the_fanout_parent_response"),
            pytest.param("database_events", True, id="secrets_in_the_other_fanout_parent_response"),
            pytest.param("droplets", False, id="nothing_to_withhold"),
        ],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean.make_tracked_session"
    )
    def test_capture_is_disabled_only_where_the_response_must_not_be_sampled(
        self, mock_session: MagicMock, endpoint: str, capture_disabled: bool
    ) -> None:
        # Sample capture records the raw response before resource maps run, so stripping a field
        # from storage does not keep it out of a sample. An endpoint holding secrets or billing
        # identity must build its own capture-off session; every other endpoint must not, leaving
        # the tracked client's default (capture on) in place.
        digitalocean_source("dop_v1_token", endpoint, team_id=1, job_id="job-1")

        if capture_disabled:
            mock_session.assert_called_once_with(redact_values=("dop_v1_token",), capture=False)
        else:
            mock_session.assert_not_called()


class TestDigitalOceanValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected",
        [
            pytest.param(200, True, id="ok"),
            pytest.param(401, False, id="unauthorized"),
            pytest.param(403, False, id="forbidden"),
            pytest.param(500, False, id="server_error"),
        ],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean.make_tracked_session"
    )
    def test_maps_status_to_validity(self, mock_session: MagicMock, status_code: int, expected: bool) -> None:
        # The status code is returned alongside validity so the caller can tell an auth rejection
        # (401/403) apart from a transient failure (429/5xx) it must not report as an invalid token.
        mock_session.return_value.get.return_value = _make_response(status_code=status_code)
        assert validate_credentials("dop_v1_token") == (expected, status_code)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean.make_tracked_session"
    )
    def test_transport_error_reports_no_status(self, mock_session: MagicMock) -> None:
        # A network failure must not surface as "token invalid"; it yields (False, None) so the
        # caller can distinguish it from a real auth rejection.
        mock_session.return_value.get.side_effect = ConnectionError("boom")
        assert validate_credentials("dop_v1_token") == (False, None)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean.make_tracked_session"
    )
    def test_sends_bearer_token(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _make_response(status_code=200)
        validate_credentials("dop_v1_token")

        _, kwargs = mock_session.return_value.get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer dop_v1_token"


class TestDigitalOceanInvoiceFanout:
    def _mock_invoice_list(self, requests_mock: Any) -> None:
        requests_mock.get(
            f"{DIGITALOCEAN_BASE_URL}/v2/customers/my/invoices",
            json={"invoices": [{"invoice_uuid": INVOICE_UUID, "amount": "27.13"}]},
        )

    def test_invoice_items_carry_their_parent_invoice_uuid(self, requests_mock: Any) -> None:
        # Line items carry no invoice reference of their own, so without the parent projection
        # (and its rename off the `_invoices_` prefix) spend can't be joined back to an invoice.
        self._mock_invoice_list(requests_mock)
        requests_mock.get(
            f"{DIGITALOCEAN_BASE_URL}/v2/customers/my/invoices/{INVOICE_UUID}",
            json={"invoice_items": [{"product": "Droplets", "amount": "12.34"}]},
        )

        assert _rows("invoice_items") == [{"product": "Droplets", "amount": "12.34", "invoice_uuid": INVOICE_UUID}]

    def test_invoice_items_paginate_within_one_invoice(self, requests_mock: Any) -> None:
        # An invoice with hundreds of resources spans pages; the child must follow
        # links.pages.next per parent rather than syncing only the first page of line items.
        self._mock_invoice_list(requests_mock)
        page_two = f"{DIGITALOCEAN_BASE_URL}/v2/customers/my/invoices/{INVOICE_UUID}?page=2"
        requests_mock.get(
            f"{DIGITALOCEAN_BASE_URL}/v2/customers/my/invoices/{INVOICE_UUID}",
            [
                {"json": {"invoice_items": [{"product": "Droplets"}], "links": {"pages": {"next": page_two}}}},
                {"json": {"invoice_items": [{"product": "Spaces"}], "links": {}}},
            ],
        )

        assert [row["product"] for row in _rows("invoice_items")] == ["Droplets", "Spaces"]

    @pytest.mark.parametrize(
        "summary",
        [
            pytest.param({"invoice_uuid": INVOICE_UUID, "amount": "27.13"}, id="body_carries_its_own_uuid"),
            pytest.param({"amount": "27.13"}, id="body_omits_the_uuid"),
        ],
    )
    def test_invoice_summary_yields_one_keyed_row_from_the_bare_object(
        self, requests_mock: Any, summary: dict[str, Any]
    ) -> None:
        # The summary endpoint returns the record as the response body rather than wrapped in a
        # list, so a list-shaped data_selector would sync nothing for it. The spec does not require
        # the body to carry `invoice_uuid`, so the parent's value is projected on; without that the
        # row can arrive with no primary key column at all.
        self._mock_invoice_list(requests_mock)
        requests_mock.get(f"{DIGITALOCEAN_BASE_URL}/v2/customers/my/invoices/{INVOICE_UUID}/summary", json=summary)

        assert _rows("invoice_summaries") == [{**summary, "invoice_uuid": INVOICE_UUID}]

    def test_both_sides_of_the_fanout_ask_for_the_max_page(self, requests_mock: Any) -> None:
        # The fan-out helper is wired with no page-size param of its own, so `per_page` rides on
        # the fan-out config. Dropping it from either side falls back to DigitalOcean's default
        # of 20 rows a page, which is 10x the requests against a 250-per-minute limit.
        invoices = requests_mock.get(
            f"{DIGITALOCEAN_BASE_URL}/v2/customers/my/invoices",
            json={"invoices": [{"invoice_uuid": INVOICE_UUID}]},
        )
        items = requests_mock.get(f"{DIGITALOCEAN_BASE_URL}/v2/customers/my/invoices/{INVOICE_UUID}", json={})
        _rows("invoice_items")

        assert invoices.last_request.qs["per_page"] == [str(PAGE_SIZE)]
        assert items.last_request.qs["per_page"] == [str(PAGE_SIZE)]


class TestDigitalOceanResourceFanouts:
    def test_project_resources_carry_their_parent_project_id(self, requests_mock: Any) -> None:
        # A resource row is only a URN and an assignment time; without the parent projection
        # (and its rename off the `_projects_` prefix) there is no project column to join on,
        # which is the whole point of the table.
        requests_mock.get(
            f"{DIGITALOCEAN_BASE_URL}/v2/projects",
            json={"projects": [{"id": PROJECT_ID, "name": "web", "is_default": True}]},
        )
        requests_mock.get(
            f"{DIGITALOCEAN_BASE_URL}/v2/projects/{PROJECT_ID}/resources",
            json={"resources": [{"urn": "do:droplet:13457723", "assigned_at": "2018-09-28T19:26:37Z"}]},
        )

        assert _rows("project_resources") == [
            {"urn": "do:droplet:13457723", "assigned_at": "2018-09-28T19:26:37Z", "project_id": PROJECT_ID}
        ]

    def test_domain_records_keep_their_own_name_alongside_the_zone(self, requests_mock: Any) -> None:
        # A record's `name` is the host part, while the parent's `name` is the zone. Projecting
        # the parent onto `domain_name` keeps both; renaming it to `name` would overwrite the host.
        requests_mock.get(f"{DIGITALOCEAN_BASE_URL}/v2/domains", json={"domains": [{"name": "example.com"}]})
        requests_mock.get(
            f"{DIGITALOCEAN_BASE_URL}/v2/domains/example.com/records",
            json={"domain_records": [{"id": 28448429, "type": "A", "name": "www", "data": "1.2.3.4"}]},
        )

        assert _rows("domain_records") == [
            {"id": 28448429, "type": "A", "name": "www", "data": "1.2.3.4", "domain_name": "example.com"}
        ]

    @pytest.mark.parametrize(
        "endpoint,child_path,child_body,expected",
        [
            pytest.param(
                "database_backups",
                "backups",
                {"backups": [{"created_at": "2019-01-11T18:42:27Z", "size_gigabytes": 0.03}]},
                {"created_at": "2019-01-11T18:42:27Z", "size_gigabytes": 0.03, "database_cluster_uuid": DATABASE_UUID},
                id="backups",
            ),
            pytest.param(
                "database_events",
                "events",
                {"events": [{"id": "pe8u2huh", "event_type": "cluster_create"}]},
                {"id": "pe8u2huh", "event_type": "cluster_create", "database_cluster_uuid": DATABASE_UUID},
                id="events",
            ),
        ],
    )
    def test_database_children_key_on_their_cluster_without_inheriting_its_credentials(
        self, requests_mock: Any, endpoint: str, child_path: str, child_body: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        # A backup has no id at all and an event id is only unique within its cluster, so the
        # cluster uuid has to reach every row or the primary key collapses across clusters. The
        # parent is `/v2/databases`, which carries connection URIs and passwords, so the
        # projection must stay narrow enough that none of them ride along into the child table.
        requests_mock.get(
            f"{DIGITALOCEAN_BASE_URL}/v2/databases",
            json={
                "databases": [
                    {
                        "id": DATABASE_UUID,
                        "name": "prod-pg",
                        "connection": {"uri": "postgresql://doadmin:secret@host:25060/defaultdb"},
                    }
                ]
            },
        )
        requests_mock.get(
            f"{DIGITALOCEAN_BASE_URL}/v2/databases/{DATABASE_UUID}/{child_path}",
            json=child_body,
        )

        assert _rows(endpoint) == [expected]

    def test_a_cluster_without_backups_does_not_fail_the_table(self, requests_mock: Any) -> None:
        # Caching and Valkey clusters support no backups, and the fan-out visits every cluster
        # on the account. Without the 404 action, one such cluster fails the whole sync for a
        # team whose other clusters back up fine.
        valkey_uuid = "0b1f8d3a-1c2e-4f5a-9b7c-2d3e4f5a6b7c"
        requests_mock.get(
            f"{DIGITALOCEAN_BASE_URL}/v2/databases",
            json={"databases": [{"id": valkey_uuid, "engine": "valkey"}, {"id": DATABASE_UUID, "engine": "pg"}]},
        )
        requests_mock.get(f"{DIGITALOCEAN_BASE_URL}/v2/databases/{valkey_uuid}/backups", status_code=404, json={})
        requests_mock.get(
            f"{DIGITALOCEAN_BASE_URL}/v2/databases/{DATABASE_UUID}/backups",
            json={"backups": [{"created_at": "2019-01-11T18:42:27Z", "size_gigabytes": 0.03}]},
        )

        assert _rows("database_backups") == [
            {"created_at": "2019-01-11T18:42:27Z", "size_gigabytes": 0.03, "database_cluster_uuid": DATABASE_UUID}
        ]
