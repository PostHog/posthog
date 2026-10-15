import io
import gzip
import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import unquote

import pytest

import pyarrow as pa
import pyarrow.parquet as pq

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_and_usage_report.aws_cost_and_usage_report import (
    NO_EXPORT_MESSAGE,
    VALIDATION_ERROR_MESSAGES,
    WRONG_REGION_MESSAGE,
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


def parquet_file(rows: list[dict[str, Any]]) -> ScriptedResponse:
    table = pa.table(
        {
            "identity_line_item_id": [row["id"] for row in rows],
            "line_item_unblended_cost": [row["cost"] for row in rows],
            "resource_tags": pa.array([row["tags"] for row in rows], type=pa.map_(pa.string(), pa.string())),
        }
    )
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return ScriptedResponse(body=buffer.getvalue(), headers={"Content-Type": "application/octet-stream"})


def csv_gz_file(text: str) -> ScriptedResponse:
    return ScriptedResponse(body=gzip.compress(text.encode()), headers={"Content-Type": "application/octet-stream"})


def s3(
    lists: Mapping[str, list[ScriptedResponse]], objects: Mapping[str, ScriptedResponse]
) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer ListObjectsV2 by its prefix, in order, and GetObject by its key. A key missing from `objects` is a 404."""
    queues = {prefix: list(answers) for prefix, answers in lists.items()}

    def respond(request: RecordedRequest) -> ScriptedResponse:
        assert request.origin == ORIGIN
        if request.param("list-type") == "2":
            queue = queues.get(request.param("prefix") or "")
            if not queue:
                raise UnexpectedRequest(f"no listing scripted for {request.url}")
            return queue.pop(0)
        return objects.get(unquote(request.path).lstrip("/"), s3_error("NoSuchKey", 404))

    return respond


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
            f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00001.snappy.parquet",
            f"{BASE}/metadata/BILLING_PERIOD=2024-04/my-export-Manifest.json",
            f"{BASE}/metadata/BILLING_PERIOD=2024-04/Manifest.json",
            f"{BASE}/data/BILLING_PERIOD=2024-04/my-export-00001.snappy.parquet",
        ]
        rows = [row for table in result.items for row in table.to_pylist()]
        assert rows == [
            {
                "identity_line_item_id": "a",
                "line_item_unblended_cost": 1.5,
                "resource_tags": '{"user:team": "web"}',
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

    @pytest.mark.parametrize(
        ("partition_listings", "expected_keys"),
        [
            pytest.param(
                {
                    f"{BASE}/data/BILLING_PERIOD=2024-03/": [
                        listing(
                            prefixes=[
                                f"{BASE}/data/BILLING_PERIOD=2024-03/20240302T010000Z-aaaa/",
                                f"{BASE}/data/BILLING_PERIOD=2024-03/20240305T010000Z-bbbb/",
                            ]
                        )
                    ],
                    f"{BASE}/data/BILLING_PERIOD=2024-03/20240305T010000Z-bbbb/": [
                        listing(
                            keys=[
                                (
                                    f"{BASE}/data/BILLING_PERIOD=2024-03/20240305T010000Z-bbbb/my-export-00001.snappy.parquet",
                                    10,
                                )
                            ]
                        )
                    ],
                },
                [f"{BASE}/data/BILLING_PERIOD=2024-03/20240305T010000Z-bbbb/my-export-00001.snappy.parquet"],
                id="create_new_reads_the_newest_delivery",
            ),
            pytest.param(
                {
                    f"{BASE}/data/BILLING_PERIOD=2024-03/": [
                        listing(
                            keys=[
                                (f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00002.snappy.parquet", 0),
                                (f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00001.snappy.parquet", 10),
                            ]
                        )
                    ],
                },
                [f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00001.snappy.parquet"],
                id="overwrite_skips_emptied_chunks",
            ),
        ],
    )
    def test_without_a_manifest_the_partition_listing_decides_the_files(
        self, partition_listings: dict[str, list[ScriptedResponse]], expected_keys: list[str]
    ) -> None:
        result = SourceDriver(AwsCostAndUsageReportSource(), config()).run(
            "cost_and_usage",
            s3(
                {f"{BASE}/data/": [listing(prefixes=[f"{BASE}/data/BILLING_PERIOD=2024-03/"])], **partition_listings},
                {key: parquet_file([{"id": "x", "cost": 1.0, "tags": None}]) for key in expected_keys},
            ),
        )

        assert result.raised is None
        assert requested_keys(result.requests)[2:] == expected_keys
        assert len(result.rows) == 1

    def test_gzip_csv_files_are_read_with_the_billing_period_added(self) -> None:
        key = f"{BASE}/data/BILLING_PERIOD=2024-03/my-export-00001.csv.gz"
        result = SourceDriver(AwsCostAndUsageReportSource(), config()).run(
            "cost_and_usage",
            s3(
                {
                    f"{BASE}/data/": [listing(prefixes=[f"{BASE}/data/BILLING_PERIOD=2024-03/"])],
                    f"{BASE}/data/BILLING_PERIOD=2024-03/": [listing(keys=[(key, 40)])],
                },
                {key: csv_gz_file("identity_line_item_id,line_item_unblended_cost\na,1.5\nb,2\n")},
            ),
        )

        assert result.raised is None
        assert [(row["identity_line_item_id"], row["billing_period"]) for row in result.rows] == [
            ("a", MARCH),
            ("b", MARCH),
        ]

    def test_a_denied_read_fails_the_run_with_the_s3_code(self) -> None:
        result = SourceDriver(AwsCostAndUsageReportSource(), config()).run(
            "cost_and_usage",
            s3({f"{BASE}/data/": [s3_error("AccessDenied", 403)]}, {}),
        )

        assert str(result.raised) == "AWS Cost and Usage Report request failed: AccessDenied - AccessDenied message"
        assert any(key in str(result.raised) for key in AwsCostAndUsageReportSource().get_non_retryable_errors())


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
