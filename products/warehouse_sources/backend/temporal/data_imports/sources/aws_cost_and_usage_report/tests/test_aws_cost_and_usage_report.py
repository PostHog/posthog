import io
import gzip
import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal
from urllib.parse import unquote

import pytest

import pyarrow as pa
import pyarrow.parquet as pq

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_and_usage_report.aws_cost_and_usage_report import (
    NO_EXPORT_MESSAGE,
    VALIDATION_ERROR_MESSAGES,
    WRONG_REGION_MESSAGE,
    CostAndUsageReportResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_and_usage_report.source import (
    AwsCostAndUsageReportSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.responders import UnexpectedRequest
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awscostandusagereport import (
    AwsCostAndUsageReportSourceConfig,
)

BUCKET = "billing-exports"
ORIGIN = f"https://{BUCKET}.s3.us-east-1.amazonaws.com"
BASE = "cur/my-export"
MARCH = dt.datetime(2024, 3, 1, tzinfo=dt.UTC)
APRIL = dt.datetime(2024, 4, 1, tzinfo=dt.UTC)


def config(**overrides: Any) -> AwsCostAndUsageReportSourceConfig:
    values: dict[str, Any] = {
        "aws_access_key_id": "AKIAEXAMPLE",
        "aws_secret_access_key": "secret",
        "aws_session_token": None,
        "aws_region": "us-east-1",
        "bucket": BUCKET,
        "prefix": "/cur/",
        "export_name": "my-export",
        "first_billing_period": "2024-03",
    }
    values.update(overrides)
    return AwsCostAndUsageReportSourceConfig(**values)


def listing(
    keys: Sequence[tuple[str, int]] = (),
    prefixes: Sequence[str] = (),
    next_token: str | None = None,
) -> ScriptedResponse:
    contents = "".join(f"<Contents><Key>{key}</Key><Size>{size}</Size></Contents>" for key, size in keys)
    common = "".join(f"<CommonPrefixes><Prefix>{prefix}</Prefix></CommonPrefixes>" for prefix in prefixes)
    truncation = (
        f"<IsTruncated>true</IsTruncated><NextContinuationToken>{next_token}</NextContinuationToken>"
        if next_token
        else "<IsTruncated>false</IsTruncated>"
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>{BUCKET}</Name>'
        f"{truncation}{contents}{common}</ListBucketResult>"
    )
    return ScriptedResponse(body=body.encode(), headers={"Content-Type": "application/xml"})


def s3_error(code: str, status: int, headers: Mapping[str, str] | None = None) -> ScriptedResponse:
    body = f'<?xml version="1.0" encoding="UTF-8"?><Error><Code>{code}</Code><Message>{code} message</Message></Error>'
    return ScriptedResponse(
        status=status, body=body.encode(), headers={"Content-Type": "application/xml", **(headers or {})}
    )


ParquetCompression = Literal["gzip", "bz2", "brotli", "lz4", "zstd", "snappy", "none"]


def parquet_file(
    rows: list[dict[str, Any]], compression: ParquetCompression | dict[str, ParquetCompression] = "snappy"
) -> ScriptedResponse:
    table = pa.table(
        {
            "identity_line_item_id": [row["id"] for row in rows],
            "line_item_unblended_cost": [row["cost"] for row in rows],
            "resource_tags": pa.array([row["tags"] for row in rows], type=pa.map_(pa.string(), pa.string())),
        }
    )
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression=compression)
    return ScriptedResponse(body=buffer.getvalue(), headers={"Content-Type": "application/octet-stream"})


def csv_gz_file(text: str) -> ScriptedResponse:
    return ScriptedResponse(body=gzip.compress(text.encode()), headers={"Content-Type": "application/octet-stream"})


def s3(
    lists: Mapping[str, list[ScriptedResponse]],
    objects: Mapping[str, ScriptedResponse | list[ScriptedResponse]],
) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer ListObjectsV2 by its prefix, in order, and GetObject by its key. A key missing from
    `objects` is a 404, and a list answers the same key's requests in turn."""
    queues = {prefix: list(answers) for prefix, answers in lists.items()}
    object_queues = {key: list(answer) for key, answer in objects.items() if isinstance(answer, list)}

    def respond(request: RecordedRequest) -> ScriptedResponse:
        assert request.origin == ORIGIN
        if request.param("list-type") == "2":
            queue = queues.get(request.param("prefix") or "")
            if not queue:
                raise UnexpectedRequest(f"no listing scripted for {request.url}")
            return queue.pop(0)
        key = unquote(request.path).lstrip("/")
        if key in object_queues:
            return object_queues[key].pop(0)
        answer = objects.get(key)
        return answer if isinstance(answer, ScriptedResponse) else s3_error("NoSuchKey", 404)

    return respond


def table_rows(items: list[Any]) -> list[dict[str, Any]]:
    """Rows of the Arrow tables a Parquet file yields; the driver only flattens lists of rows."""
    return [row for table in items for row in table.to_pylist()]


def requested_keys(requests: list[RecordedRequest]) -> list[str]:
    return [unquote(request.path).lstrip("/") for request in requests if request.param("list-type") is None]


class TestSync:
    def test_reads_the_files_each_manifest_lists_for_every_period_from_the_first_one(self) -> None:
        manifest = {
            "dataFiles": [
                f"s3://{BUCKET}/{BASE}/data/BILLING_PERIOD=2024-03/my-export-00001.snappy.parquet",
                "s3://another-bucket/elsewhere/my-export-00001.snappy.parquet",
            ],
            "additionalOutputFiles": [{"path": f"{BASE}/metadata/BILLING_PERIOD=2024-03/my-export-create-table.sql"}],
        }
        result = SourceDriver(AwsCostAndUsageReportSource(), config()).run(
            "cost_and_usage",
            s3(
                {
                    f"{BASE}/data/": [
                        listing(prefixes=[f"{BASE}/data/BILLING_PERIOD=2024-02/"], next_token="t2"),
                        listing(
                            prefixes=[f"{BASE}/data/BILLING_PERIOD=2024-04/", f"{BASE}/data/BILLING_PERIOD=2024-03/"]
                        ),
                    ],
                },
                {
                    f"{BASE}/metadata/BILLING_PERIOD=2024-03/my-export-Manifest.json": ScriptedResponse(json=manifest),
                    f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00001.snappy.parquet": parquet_file(
                        [
                            {"id": "a", "cost": 1.5, "tags": [("user:team", "web")]},
                            {"id": "b", "cost": 2.0, "tags": None},
                        ]
                    ),
                    f"{BASE}/metadata/BILLING_PERIOD=2024-04/Manifest.json": ScriptedResponse(
                        json={"dataFiles": [f"{BASE}/data/BILLING_PERIOD=2024-04/my-export-00001.snappy.parquet"]}
                    ),
                    f"{BASE}/data/BILLING_PERIOD=2024-04/my-export-00001.snappy.parquet": parquet_file(
                        [{"id": "c", "cost": 0.25, "tags": []}]
                    ),
                },
            ),
        )

        assert result.raised is None
        first_list = result.requests[0]
        assert (first_list.param("prefix"), first_list.param("delimiter")) == (f"{BASE}/data/", "/")
        assert result.requests[1].param("continuation-token") == "t2"
        # February predates the first billing period; April's manifest uses the bare name.
        assert requested_keys(result.requests) == [
            f"{BASE}/metadata/BILLING_PERIOD=2024-03/my-export-Manifest.json",
            f"{BASE}/metadata/BILLING_PERIOD=2024-03/Manifest.json",
            f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00001.snappy.parquet",
            f"{BASE}/metadata/BILLING_PERIOD=2024-04/my-export-Manifest.json",
            f"{BASE}/metadata/BILLING_PERIOD=2024-04/Manifest.json",
            f"{BASE}/data/BILLING_PERIOD=2024-04/my-export-00001.snappy.parquet",
        ]
        assert table_rows(result.items) == [
            {
                "identity_line_item_id": "a",
                "line_item_unblended_cost": 1.5,
                "resource_tags": '{"user:team":"web"}',
                "billing_period": MARCH,
            },
            {
                "identity_line_item_id": "b",
                "line_item_unblended_cost": 2.0,
                "resource_tags": None,
                "billing_period": MARCH,
            },
            {
                "identity_line_item_id": "c",
                "line_item_unblended_cost": 0.25,
                "resource_tags": "{}",
                "billing_period": APRIL,
            },
        ]
        assert "authorization" in first_list.headers
        assert result.response is not None and result.response.partition_keys == ["billing_period"]

    def test_a_period_still_being_delivered_is_skipped_and_one_with_no_manifest_anywhere_fails(self) -> None:
        march_file = f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00001.snappy.parquet"
        periods = listing(prefixes=[f"{BASE}/data/BILLING_PERIOD=2024-03/", f"{BASE}/data/BILLING_PERIOD=2024-04/"])

        # April has data files but no manifest yet: AWS is still delivering it.
        partly = SourceDriver(AwsCostAndUsageReportSource(), config()).run(
            "cost_and_usage",
            s3(
                {f"{BASE}/data/": [periods]},
                {
                    f"{BASE}/metadata/BILLING_PERIOD=2024-03/Manifest.json": ScriptedResponse(
                        json={"dataFiles": [march_file]}
                    ),
                    march_file: parquet_file([{"id": "x", "cost": 1.0, "tags": None}]),
                },
            ),
        )

        assert partly.raised is None
        assert [row["billing_period"] for row in table_rows(partly.items)] == [MARCH]
        assert not any("BILLING_PERIOD=2024-04/" in key and "/data/" in key for key in requested_keys(partly.requests))

        periods = listing(prefixes=[f"{BASE}/data/BILLING_PERIOD=2024-03/", f"{BASE}/data/BILLING_PERIOD=2024-04/"])
        nothing = SourceDriver(AwsCostAndUsageReportSource(), config()).run(
            "cost_and_usage", s3({f"{BASE}/data/": [periods]}, {})
        )

        assert str(nothing.raised).startswith("AWS Cost and Usage Report request failed: NoManifest")

    def test_gzip_csv_cells_take_the_names_and_types_a_parquet_file_would_have(self) -> None:
        # A FOCUS export names columns in PascalCase. The pipeline snake-cases Parquet columns, so CSV
        # columns must land under the same names or one measure splits across two columns.
        key = f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00001.csv.gz"
        manifest = {
            "dataFiles": [key],
            "columns": [
                {"name": "BillingAccountId", "type": "string"},
                {"name": "BilledCost", "type": "double"},
                # 30 decimal places exceed the 28-digit default decimal context.
                {"name": "ConsumedQuantity", "type": "decimal(38,30)"},
                {"name": "x_LeaseContractLength", "type": "bigint"},
                {"name": "ChargePeriodStart", "type": "timestamp"},
                {"name": "x_UsageDate", "type": "date"},
            ],
        }
        result = SourceDriver(AwsCostAndUsageReportSource(), config()).run(
            "cost_and_usage",
            s3(
                {f"{BASE}/data/": [listing(prefixes=[f"{BASE}/data/BILLING_PERIOD=2024-03/"])]},
                {
                    f"{BASE}/metadata/BILLING_PERIOD=2024-03/my-export-Manifest.json": ScriptedResponse(json=manifest),
                    key: csv_gz_file(
                        "BillingAccountId,BilledCost,ConsumedQuantity,x_LeaseContractLength,ChargePeriodStart,x_UsageDate\n"
                        "012345678901,1.5,24,3,2024-03-01T00:00:00Z,2024-03-01\n"
                        "012345678901,,not-a-number,,,\n"
                    ),
                },
            ),
        )

        assert result.raised is None
        assert table_rows(result.items) == [
            {
                "billing_account_id": "012345678901",
                "billed_cost": 1.5,
                "consumed_quantity": 24.0,
                "x_lease_contract_length": 3,
                "charge_period_start": MARCH,
                "x_usage_date": dt.date(2024, 3, 1),
                "billing_period": MARCH,
            },
            {
                "billing_account_id": "012345678901",
                "billed_cost": None,
                "consumed_quantity": None,
                "x_lease_contract_length": None,
                "charge_period_start": None,
                "x_usage_date": None,
                "billing_period": MARCH,
            },
        ]

    def test_a_file_rewritten_after_its_manifest_stops_the_run_instead_of_mixing_deliveries(self) -> None:
        key = f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00001.snappy.parquet"
        manifest_written = "Wed, 06 Mar 2024 10:00:00 GMT"
        result = SourceDriver(AwsCostAndUsageReportSource(), config()).run(
            "cost_and_usage",
            s3(
                {f"{BASE}/data/": [listing(prefixes=[f"{BASE}/data/BILLING_PERIOD=2024-03/"])]},
                {
                    f"{BASE}/metadata/BILLING_PERIOD=2024-03/my-export-Manifest.json": ScriptedResponse(
                        json={"dataFiles": [key]}, headers={"Last-Modified": manifest_written}
                    ),
                    # AWS overwrote the file after the manifest we read, as an "overwrite" export does.
                    key: s3_error("PreconditionFailed", 412),
                },
            ),
        )

        download = next(request for request in result.requests if unquote(request.path).endswith(".parquet"))
        assert download.headers["if-unmodified-since"] == manifest_written
        assert str(result.raised).startswith("AWS Cost and Usage Report request failed: DeliveryInProgress")

    def test_a_parquet_file_with_a_brotli_column_stops_the_run_before_any_row_is_yielded(self) -> None:
        key = f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00001.snappy.parquet"
        result = SourceDriver(AwsCostAndUsageReportSource(), config()).run(
            "cost_and_usage",
            s3(
                {f"{BASE}/data/": [listing(prefixes=[f"{BASE}/data/BILLING_PERIOD=2024-03/"])]},
                {
                    f"{BASE}/metadata/BILLING_PERIOD=2024-03/my-export-Manifest.json": ScriptedResponse(
                        json={"dataFiles": [key]}
                    ),
                    key: parquet_file(
                        [{"id": "x", "cost": 1.0, "tags": None}], compression={"line_item_unblended_cost": "brotli"}
                    ),
                },
            ),
        )

        assert str(result.raised).startswith("AWS Cost and Usage Report request failed: UnsupportedCompression")
        assert table_rows(result.items) == []
        assert any(
            str(result.raised).startswith(prefix) for prefix in AwsCostAndUsageReportSource().get_non_retryable_errors()
        )

    def test_a_run_mixing_parquet_and_csv_periods_yields_arrow_tables_only(self) -> None:
        march = f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00001.csv.gz"
        april = f"{BASE}/data/BILLING_PERIOD=2024-04/my-export-00001.snappy.parquet"
        result = SourceDriver(AwsCostAndUsageReportSource(), config()).run(
            "cost_and_usage",
            s3(
                {
                    f"{BASE}/data/": [
                        listing(
                            prefixes=[f"{BASE}/data/BILLING_PERIOD=2024-03/", f"{BASE}/data/BILLING_PERIOD=2024-04/"]
                        )
                    ]
                },
                {
                    f"{BASE}/metadata/BILLING_PERIOD=2024-03/Manifest.json": ScriptedResponse(
                        json={"dataFiles": [march], "columns": [{"name": "line_item_unblended_cost", "type": "double"}]}
                    ),
                    march: csv_gz_file("identity_line_item_id,line_item_unblended_cost\na,1.5\n"),
                    f"{BASE}/metadata/BILLING_PERIOD=2024-04/Manifest.json": ScriptedResponse(
                        json={"dataFiles": [april]}
                    ),
                    april: parquet_file([{"id": "b", "cost": 2.0, "tags": None}]),
                },
            ),
        )

        assert result.raised is None
        assert all(isinstance(item, pa.Table) for item in result.items)
        assert [
            (row["identity_line_item_id"], row["line_item_unblended_cost"]) for row in table_rows(result.items)
        ] == [
            ("a", 1.5),
            ("b", 2.0),
        ]

    def test_a_download_cut_off_mid_body_is_retried_for_that_file_only(self) -> None:
        key = f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00001.snappy.parquet"
        # A chunked body with no terminating chunk fails after the headers, past the transport's retry.
        cut_off = ScriptedResponse(body=b"5\r\nPAR1", headers={"Transfer-Encoding": "chunked"})
        result = SourceDriver(AwsCostAndUsageReportSource(), config()).run(
            "cost_and_usage",
            s3(
                {f"{BASE}/data/": [listing(prefixes=[f"{BASE}/data/BILLING_PERIOD=2024-03/"])]},
                {
                    f"{BASE}/metadata/BILLING_PERIOD=2024-03/Manifest.json": ScriptedResponse(
                        json={"dataFiles": [key]}
                    ),
                    key: [cut_off, parquet_file([{"id": "x", "cost": 1.0, "tags": None}])],
                },
            ),
        )

        assert result.raised is None
        assert requested_keys(result.requests).count(key) == 2
        assert [row["identity_line_item_id"] for row in table_rows(result.items)] == ["x"]

    def test_a_denied_read_fails_the_run_with_the_s3_code(self) -> None:
        result = SourceDriver(AwsCostAndUsageReportSource(), config()).run(
            "cost_and_usage",
            s3({f"{BASE}/data/": [s3_error("AccessDenied", 403)]}, {}),
        )

        assert str(result.raised) == "AWS Cost and Usage Report request failed: AccessDenied - AccessDenied message"


def probe(c: AwsCostAndUsageReportSourceConfig) -> tuple[bool, str | None]:
    return validate_credentials(
        c.aws_access_key_id,
        c.aws_secret_access_key,
        c.aws_session_token,
        c.aws_region,
        c.bucket,
        c.prefix,
        c.export_name,
        c.first_billing_period,
    )


class TestDeliveries:
    MANIFEST_KEY = f"{BASE}/metadata/BILLING_PERIOD=2024-03/my-export-Manifest.json"
    FIRST = f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00001.snappy.parquet"
    SECOND = f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00002.snappy.parquet"
    WRITTEN = "Wed, 06 Mar 2024 10:00:00 GMT"

    def _run(self, objects: Mapping[str, ScriptedResponse], resume_state: Any = None) -> Any:
        periods = listing(prefixes=[f"{BASE}/data/BILLING_PERIOD=2024-03/"])
        return SourceDriver(AwsCostAndUsageReportSource(), config()).run(
            "cost_and_usage", s3({f"{BASE}/data/": [periods]}, objects), resume_state=resume_state
        )

    @pytest.mark.parametrize(
        "saved_written, expected_ids, raised",
        [
            ("Wed, 06 Mar 2024 10:00:00 GMT", ["b"], None),
            # AWS delivered the month again, so the saved file and batch point into other files.
            ("Tue, 05 Mar 2024 10:00:00 GMT", [], "DeliveryInProgress"),
        ],
    )
    def test_a_resumed_run_continues_after_its_last_batch_only_within_the_same_delivery(
        self, saved_written: str, expected_ids: list[str], raised: str | None
    ) -> None:
        manifest = ScriptedResponse(
            json={"dataFiles": [self.FIRST, self.SECOND]}, headers={"Last-Modified": self.WRITTEN}
        )
        result = self._run(
            {
                self.MANIFEST_KEY: manifest,
                self.FIRST: parquet_file([{"id": "a", "cost": 1.0, "tags": []}]),
                self.SECOND: parquet_file([{"id": "b", "cost": 2.0, "tags": []}]),
            },
            resume_state=CostAndUsageReportResumeConfig(
                billing_period="2024-03", manifest_last_modified=saved_written, file_index=0, batch_index=1
            ),
        )

        assert [row["identity_line_item_id"] for row in table_rows(result.items)] == expected_ids
        if raised is None:
            assert result.raised is None
            assert result.saved_states[-1] == CostAndUsageReportResumeConfig(
                billing_period="2024-03", manifest_last_modified=self.WRITTEN, file_index=1, batch_index=1
            )
            # A retry after a failed finalization must read again, not resume past every batch.
            assert result.final_state is None
        else:
            assert raised in str(result.raised)
            assert result.final_state is None

    @pytest.mark.parametrize(
        "manifest",
        [
            ScriptedResponse(body=b"{not json", headers={"Content-Type": "application/json"}),
            ScriptedResponse(json={"dataFiles": []}),
        ],
    )
    def test_a_manifest_with_no_readable_file_list_fails_instead_of_dropping_the_month(
        self, manifest: ScriptedResponse
    ) -> None:
        result = self._run({self.MANIFEST_KEY: manifest})

        assert str(result.raised).startswith("AWS Cost and Usage Report request failed: ManifestUnreadable")
        assert result.items == []

    def test_the_newer_manifest_wins_when_an_export_left_both_names_behind(self) -> None:
        result = self._run(
            {
                self.MANIFEST_KEY: ScriptedResponse(
                    json={"dataFiles": [self.FIRST]}, headers={"Last-Modified": "Mon, 04 Mar 2024 10:00:00 GMT"}
                ),
                f"{BASE}/metadata/BILLING_PERIOD=2024-03/Manifest.json": ScriptedResponse(
                    json={"dataFiles": [self.SECOND]}, headers={"Last-Modified": self.WRITTEN}
                ),
                self.SECOND: parquet_file([{"id": "b", "cost": 2.0, "tags": []}]),
            }
        )

        assert result.raised is None
        assert [row["identity_line_item_id"] for row in table_rows(result.items)] == ["b"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ({"aws_secret_access_key": ""}, "AWS access key ID and secret access key are required"),
            ({"aws_region": "Frankfurt"}, "Enter an AWS region code, for example us-east-1."),
            ({"bucket": "s3://billing-exports/cur"}, "Enter the bucket name only, without s3:// or a path."),
            ({"export_name": " / "}, "Enter the name of the data export."),
            ({"first_billing_period": "2024-13"}, "Enter the first billing period as YYYY-MM, for example 2024-01."),
        ],
    )
    def test_local_checks_fail_before_any_request(self, overrides: dict[str, Any], expected: str) -> None:
        with scripted_network([]) as network:
            assert probe(config(**overrides)) == (False, expected)

        assert network.requests == 0

    @pytest.mark.parametrize(
        ("answer", "expected"),
        [
            (listing(prefixes=[f"{BASE}/data/BILLING_PERIOD=2024-03/"]), (True, None)),
            (listing(), (False, NO_EXPORT_MESSAGE)),
            (s3_error("AccessDenied", 403), (False, VALIDATION_ERROR_MESSAGES["AccessDenied"])),
            (s3_error("NoSuchBucket", 404), (False, VALIDATION_ERROR_MESSAGES["NoSuchBucket"])),
            (
                s3_error("PermanentRedirect", 301, {"x-amz-bucket-region": "eu-west-1"}),
                (False, "The bucket is in eu-west-1. Set the AWS region to eu-west-1."),
            ),
            (s3_error("AuthorizationHeaderMalformed", 400), (False, WRONG_REGION_MESSAGE)),
        ],
    )
    def test_the_probe_lists_the_export_and_translates_s3_errors(
        self, answer: ScriptedResponse, expected: tuple[bool, str | None]
    ) -> None:
        with scripted_network([answer]) as network:
            assert probe(config()) == expected

        request = network.requests_log[0]
        assert request.origin == ORIGIN
        assert (request.param("prefix"), request.param("max-keys")) == (f"{BASE}/data/", "1")

    @pytest.mark.parametrize(
        ("bucket", "region", "origin", "path"),
        [
            ("billing.exports", "us-east-1", "https://s3.us-east-1.amazonaws.com", "/billing.exports/"),
            (BUCKET, "cn-north-1", f"https://{BUCKET}.s3.cn-north-1.amazonaws.com.cn", "/"),
        ],
    )
    def test_the_endpoint_follows_the_bucket_name_and_the_aws_partition(
        self, bucket: str, region: str, origin: str, path: str
    ) -> None:
        with scripted_network([listing(prefixes=["x/"])]) as network:
            assert probe(config(bucket=bucket, aws_region=region)) == (True, None)

        request = network.requests_log[0]
        assert (request.origin, request.path) == (origin, path)
