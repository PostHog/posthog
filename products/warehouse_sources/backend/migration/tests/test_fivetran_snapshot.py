import json
import tracemalloc
from typing import Any

import pytest
from unittest.mock import MagicMock

from django.test import SimpleTestCase

import requests
import requests_mock
from parameterized import parameterized

from products.warehouse_sources.backend.facade.contracts import (
    MigrationConnectionUpload,
    WarehouseMigrationUploadTooLargeError,
)
from products.warehouse_sources.backend.migration.fivetran.client import (
    FIVETRAN_API_URL,
    FivetranAPIError,
    FivetranAuthError,
    FivetranClient,
    FivetranCredentials,
    FivetranWriteBlockedError,
)
from products.warehouse_sources.backend.migration.fivetran.snapshot import (
    SnapshotStoppedError,
    fetch_snapshot,
    merge_upload,
    parse_connection,
)
from products.warehouse_sources.backend.migration.secrets import strip_secrets
from products.warehouse_sources.backend.migration.types import ScheduleKind, VendorSchedule, VendorSnapshot

FAKE_API_KEY = "fake-api-key"
FAKE_API_SECRET = "fake-api-secret"
UNMASKED_SOURCE_PASSWORD = "fake-unmasked-source-password"
UNMASKED_TUNNEL_KEY = "fake-unmasked-tunnel-key"
UNMASKED_DESTINATION_KEY = "fake-unmasked-destination-key"


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"json": {"code": "Success", "data": data}}


def _page(items: list[dict[str, Any]], next_cursor: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"items": items}
    if next_cursor:
        data["next_cursor"] = next_cursor
    return _ok(data)


def _client() -> FivetranClient:
    return FivetranClient(FivetranCredentials(api_key=FAKE_API_KEY, api_secret=FAKE_API_SECRET))


class TestFetchSnapshot(SimpleTestCase):
    def _mock_account(self, m: requests_mock.Mocker) -> None:
        m.get(f"{FIVETRAN_API_URL}/account/info", **_ok({"account_id": "acct_example", "account_name": "Example"}))
        m.get(
            f"{FIVETRAN_API_URL}/groups",
            **_page([{"id": "grp_warehouse", "name": "Main warehouse"}, {"id": "grp_empty", "name": "Unused"}]),
        )
        m.get(
            f"{FIVETRAN_API_URL}/destinations/grp_warehouse",
            **_ok(
                {
                    "id": "grp_warehouse",
                    "service": "snowflake",
                    "region": "AWS_US_EAST_1",
                    "time_zone_offset": "+3",
                    "config": {
                        "host": "acct.example.com",
                        "database": "ANALYTICS",
                        "password": "******",
                        "private_key": UNMASKED_DESTINATION_KEY,
                        # Not a key PostHog reads for Snowflake, so it is dropped whatever its name says.
                        "auth_secret_holder": UNMASKED_DESTINATION_KEY,
                        "snowflake_cloud": "AWS",
                    },
                }
            ),
        )
        m.get(f"{FIVETRAN_API_URL}/destinations/grp_empty", status_code=404, json={"message": "Not found"})

    def _mock_connections(self, m: requests_mock.Mocker) -> None:
        m.get(
            f"{FIVETRAN_API_URL}/connections",
            [_page([{"id": "conn_pg"}], next_cursor="cursor_2"), _page([{"id": "conn_folder"}])],
        )
        m.get(
            f"{FIVETRAN_API_URL}/connections/conn_pg",
            **_ok(
                {
                    "id": "conn_pg",
                    "service": "postgres",
                    "schema": "app_db",
                    "group_id": "grp_warehouse",
                    "paused": False,
                    "schedule_type": "auto",
                    "schedule": {"schedule_type": "TIME_OF_DAY", "time_of_day": "02:00"},
                    "status": {"setup_state": "connected"},
                    "config": {
                        "host": "db.example.com",
                        "port": 5432,
                        "password": UNMASKED_SOURCE_PASSWORD,
                        "tunnel_host": "bastion.example.com",
                        "tunnel_private_key": UNMASKED_TUNNEL_KEY,
                        "update_method": "XMIN",
                        # Not a Postgres setting in PostHog, so the snapshot leaves it out.
                        "connection_label": "app",
                    },
                }
            ),
        )
        m.get(
            f"{FIVETRAN_API_URL}/connections/conn_pg/schemas",
            **_ok(
                {
                    "schema_change_handling": "ALLOW_COLUMNS",
                    "schemas": {
                        "public": {
                            "enabled": True,
                            "tables": {
                                "orders": {
                                    "enabled": True,
                                    "sync_mode": "SOFT_DELETE",
                                    "columns": {"card_number": {"enabled": False, "hashed": False}},
                                    "row_filter": {
                                        "column_clauses": [
                                            {"column": "status", "operator": "EQUALS", "values": ["ACTIVE"]}
                                        ]
                                    },
                                }
                            },
                        },
                        "archive": {"enabled": False, "tables": {"old_orders": {"enabled": True}}},
                    },
                }
            ),
        )
        m.get(
            f"{FIVETRAN_API_URL}/connections/conn_folder",
            **_ok({"id": "conn_folder", "service": "google_drive", "schema": "drive", "sync_frequency": 360}),
        )
        m.get(f"{FIVETRAN_API_URL}/connections/conn_folder/schemas", status_code=404, json={"message": "Not found"})

    def test_stops_before_the_next_connection_once_the_caller_gives_up(self) -> None:
        answers = iter([True, False])
        with requests_mock.Mocker() as m:
            self._mock_account(m)
            self._mock_connections(m)
            with pytest.raises(SnapshotStoppedError):
                fetch_snapshot(_client(), keep_going=lambda: next(answers))

        requested = {request.path for request in m.request_history}
        assert "/v1/connections/conn_pg" in requested
        assert "/v1/connections/conn_folder" not in requested

    def test_reads_whole_account_and_stores_no_secret(self) -> None:
        with requests_mock.Mocker() as m:
            self._mock_account(m)
            self._mock_connections(m)
            snapshot = fetch_snapshot(_client())
            requested_cursors = [r.qs.get("cursor") for r in m.request_history if r.path == "/v1/connections"]

        assert requested_cursors == [None, ["cursor_2"]]
        assert [d.id for d in snapshot.destinations] == ["grp_warehouse"]
        assert snapshot.destinations[0].config == {"host": "acct.example.com", "database": "ANALYTICS"}
        assert [c.id for c in snapshot.connections] == ["conn_pg", "conn_folder"]

        pg, folder = snapshot.connections
        assert pg.config == {
            "host": "db.example.com",
            "port": 5432,
            "tunnel_host": "bastion.example.com",
            "update_method": "XMIN",
        }
        assert pg.schedule == VendorSchedule(kind=ScheduleKind.TIME_OF_DAY, time_of_day_utc="23:00")
        assert pg.schema_change_handling == "ALLOW_COLUMNS"
        assert [(t.schema_name, t.name, t.enabled) for t in pg.tables] == [
            ("public", "orders", True),
            ("archive", "old_orders", False),
        ]
        orders = pg.tables[0]
        assert [c.name for c in orders.columns if not c.enabled] == ["card_number"]
        assert orders.row_filter is not None
        assert orders.row_filter.clauses[0].values == ("ACTIVE",)
        assert folder.tables_available is False

        stored = json.dumps(snapshot.to_json())
        for secret in (UNMASKED_SOURCE_PASSWORD, UNMASKED_TUNNEL_KEY, UNMASKED_DESTINATION_KEY, "******"):
            assert secret not in stored
        assert VendorSnapshot.from_json(json.loads(stored)) == snapshot

    @parameterized.expand(
        [
            ("auth_error", 403, {"message": "No"}, FivetranAuthError),
            ("other_error", 400, {"message": "No"}, FivetranAPIError),
            ("non_object_body", 200, [], FivetranAPIError),
        ]
    )
    def test_schema_config_error_other_than_404_stops_the_crawl(
        self, _name: str, status_code: int, body: Any, error: type[Exception]
    ) -> None:
        with requests_mock.Mocker() as m:
            self._mock_account(m)
            self._mock_connections(m)
            m.get(f"{FIVETRAN_API_URL}/connections/conn_pg/schemas", status_code=status_code, json=body)
            with pytest.raises(error):
                fetch_snapshot(_client())


class TestMergeUpload(SimpleTestCase):
    def test_refuses_a_schema_name_repeated_in_every_table_without_encoding_all_of_it(self) -> None:
        # About 120 KB as uploaded, and about 200 MB once each of the 2,000 tables carries the schema name.
        schema_config = {"schemas": {"s" * 100_000: {"enabled": True, "tables": {f"t{i}": {} for i in range(2_000)}}}}
        connection = {"id": "conn_a", "service": "postgres", "schema": "public"}
        upload = MigrationConnectionUpload(connection=connection, schema_config=schema_config)
        # The first call imports modules lazily, which would count toward the peak.
        merge_upload(None, account=None, destinations=[], connections=[MigrationConnectionUpload(connection, None)])
        tracemalloc.start()
        try:
            with pytest.raises(WarehouseMigrationUploadTooLargeError):
                merge_upload(None, account=None, destinations=[], connections=[upload])
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert peak < 50_000_000


class TestConnectionConfig(SimpleTestCase):
    @parameterized.expand(
        [
            # ShipStation's `username` holds its API key; no PostHog field reads it, so it is never kept.
            ("unread_key_of_a_matched_source", "shipstation", {"username": "fake", "update_method": "API"}),
            ("unmatched_service", "not_a_fivetran_service", {"host": "db.example.com", "update_method": "API"}),
        ]
    )
    def test_keeps_only_keys_the_plan_reads(self, _name: str, service: str, config: dict[str, Any]) -> None:
        connection = parse_connection(
            {"id": "conn_example", "service": service, "config": config}, None, utc_offset_hours=0
        )
        assert connection.config == {"update_method": "API"}


class TestParseSchedule(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "manual_schedule_type",
                {"schedule_type": "manual", "sync_frequency": 60},
                0,
                VendorSchedule(kind=ScheduleKind.MANUAL),
            ),
            (
                "manual_schedule_object",
                {"schedule": {"schedule_type": "MANUAL"}},
                0,
                VendorSchedule(kind=ScheduleKind.MANUAL),
            ),
            (
                "cron",
                {"schedule": {"schedule_type": "CRON", "cron": "0 */6 * * *", "time_zone": "Europe/Prague"}},
                0,
                VendorSchedule(kind=ScheduleKind.CRON, cron="0 */6 * * *", time_zone="Europe/Prague"),
            ),
            (
                "cron_without_zone_runs_in_destination_offset",
                {"schedule": {"schedule_type": "CRON", "cron": "0 6 * * *"}},
                -5,
                VendorSchedule(kind=ScheduleKind.CRON, cron="0 6 * * *", time_zone="UTC-05:00"),
            ),
            (
                "time_of_day_negative_offset_wraps",
                {"schedule": {"schedule_type": "TIME_OF_DAY", "time_of_day": "22:30"}},
                -5,
                VendorSchedule(kind=ScheduleKind.TIME_OF_DAY, time_of_day_utc="03:30"),
            ),
            (
                "time_of_day_crossing_midnight_moves_the_day",
                {"schedule": {"schedule_type": "TIME_OF_DAY", "time_of_day": "22:30", "days_of_week": ["SUNDAY"]}},
                -5,
                VendorSchedule(kind=ScheduleKind.TIME_OF_DAY, time_of_day_utc="03:30", days_of_week=("MONDAY",)),
            ),
            (
                "interval_with_some_days",
                {"schedule": {"schedule_type": "INTERVAL", "interval": 360, "days_of_week": ["MONDAY", "FRIDAY"]}},
                0,
                VendorSchedule(kind=ScheduleKind.INTERVAL, interval_minutes=360, days_of_week=("MONDAY", "FRIDAY")),
            ),
            (
                "all_days_means_every_day",
                {
                    "schedule": {
                        "schedule_type": "INTERVAL",
                        "interval": 60,
                        "days_of_week": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"],
                    }
                },
                0,
                VendorSchedule(kind=ScheduleKind.INTERVAL, interval_minutes=60),
            ),
            (
                "legacy_daily_sync_time_is_already_utc",
                {"sync_frequency": 1440, "daily_sync_time": "14:00"},
                3,
                VendorSchedule(kind=ScheduleKind.INTERVAL, interval_minutes=1440, time_of_day_utc="14:00"),
            ),
        ]
    )
    def test_schedule(self, _name: str, raw: dict[str, Any], offset: int, expected: VendorSchedule) -> None:
        connection = parse_connection({"id": "conn_example", **raw}, None, utc_offset_hours=offset)
        assert connection.schedule == expected


class TestStripSecrets(SimpleTestCase):
    @parameterized.expand(
        [
            ("masked_value_under_innocent_key", {"username": "****"}, {}),
            ("secret_key_with_real_value", {"client_secret": "fake"}, {}),
            (
                "nested_and_listed",
                {"files": [{"pgp_pass_phrase": "fake", "pattern": "*.csv"}, "******"]},
                {"files": [{"pattern": "*.csv"}]},
            ),
            ("key_suffix", {"sasl_plain_key": "fake", "account_key": "fake", "api_keys": ["fake"]}, {}),
            ("numbered_key", {"api_key_2": "fake", "tde_private_key_backup": "fake", "keystore": "fake"}, {}),
            ("named_token", {"pat": "fake", "query_param_value": "fake"}, {}),
            ("token_in_url", {"blob_sas_url": "https://acct.blob.core.example.com/c?sv=2024&sig=fake"}, {}),
            ("encoded_token_name_in_url", {"blob_sas_url": "https://acct.blob.core.example.com/c?%73ig=fake"}, {}),
            ("camel_case", {"apiKey": "fake", "privateKey": "fake"}, {}),
            ("auth_object", {"auth": {"client_id": "fake"}, "authorization": "fake"}, {}),
            ("password_in_url", {"uri": "postgres://reader:fake@db.example.com/app"}, {}),
            ("password_in_a_later_url", {"note": "see https://docs.example.com then ftp://u:fake@h"}, {}),
            # A backtracking pattern takes minutes on this.
            (
                "long_colon_run_is_not_secret",
                {"host": "https://" + ":" * 100_000},
                {"host": "https://" + ":" * 100_000},
            ),
            ("password_in_url_without_user", {"uri": "redis://:fake@cache.example.com:6379"}, {}),
            ("percent_encoded_password_in_url", {"jdbc_url": "postgres://reader%3Afake@db.example.com/app"}, {}),
            ("at_sign_in_the_user", {"jdbc_url": "postgres://reader@corp:fake@db.example.com/app"}, {}),
            (
                "credential_in_url_query",
                {
                    "jdbc_url": "jdbc:mysql://db.example.com/app?user=reader&password=fake",
                    "presigned": "https://bucket.example.com/f.csv?X-Amz-Expires=60&X-Amz-Signature=fake",
                },
                {},
            ),
            (
                "service_specific_credentials",
                {
                    "service_authentication": "fake",
                    "dsv_service_auth": "fake",
                    "shard_authorization_id": "fake",
                    "primary_key": "fake",
                    "app_id": "fake",
                },
                {},
            ),
            (
                "client_certificate_is_secret_but_ca_is_not",
                {
                    "client_certificate": "fake",
                    "sslCert": "fake",
                    "ca_cert": "-----BEGIN",
                    "ssl_root_cert": "-----BEGIN",
                },
                {"ca_cert": "-----BEGIN", "ssl_root_cert": "-----BEGIN"},
            ),
            (
                "public_key_is_not_secret",
                {"public_key": "ssh-rsa AAAA", "primary_keys": ["id"], "host": "db.example.com"},
                {"public_key": "ssh-rsa AAAA", "primary_keys": ["id"], "host": "db.example.com"},
            ),
        ]
    )
    def test_strip(self, _name: str, config: dict[str, Any], expected: dict[str, Any]) -> None:
        assert strip_secrets(config) == expected


class TestReadOnlyClient(SimpleTestCase):
    @parameterized.expand(
        [(method, scheme) for method in ("POST", "PATCH", "PUT", "DELETE") for scheme in ("http", "https")]
    )
    def test_write_methods_never_leave_posthog(self, method: str, scheme: str) -> None:
        # A closed local port: if the guard ever fails, the call errors here instead of reaching Fivetran.
        base_url = f"{scheme}://127.0.0.1:9"
        client = FivetranClient(
            FivetranCredentials(api_key=FAKE_API_KEY, api_secret=FAKE_API_SECRET), base_url=base_url
        )
        with pytest.raises(FivetranWriteBlockedError):
            client._session.request(method, f"{base_url}/connections/conn_example")

    def test_a_get_reaches_the_wrapped_adapter_with_its_options(self) -> None:
        client = FivetranClient(FivetranCredentials(api_key=FAKE_API_KEY, api_secret=FAKE_API_SECRET))
        adapter = client._session.get_adapter("https://")
        inner = MagicMock()
        adapter._inner = inner  # type: ignore[attr-defined]

        request = requests.Request("GET", f"{FIVETRAN_API_URL}/account/info").prepare()
        adapter.send(request, timeout=(5, 30), verify=True)

        inner.send.assert_called_once_with(request, timeout=(5, 30), verify=True)
