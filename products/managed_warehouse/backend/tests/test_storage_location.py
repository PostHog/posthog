import pytest

from products.managed_warehouse.backend.logic.sql_editor_trino import location_from_show_create_table
from products.managed_warehouse.backend.storage_location import delta_table_root, normalize_s3_location


@pytest.mark.parametrize(
    "location, expected",
    [
        ("s3://bucket/delta/invoices", "s3://bucket/delta/invoices"),
        ("s3://bucket/delta/invoices/", "s3://bucket/delta/invoices"),
        ("S3A://bucket/delta/invoices", "s3://bucket/delta/invoices"),
        ("https://bucket.s3.amazonaws.com/delta/invoices/", "s3://bucket/delta/invoices"),
        ("https://my.bucket.s3.eu-central-1.amazonaws.com/delta/invoices", "s3://my.bucket/delta/invoices"),
        ("https://bucket.s3-eu-west-1.amazonaws.com/delta/invoices", "s3://bucket/delta/invoices"),
        ("https://s3.eu-central-1.amazonaws.com/bucket/delta/invoices", "s3://bucket/delta/invoices"),
        ("https://s3.amazonaws.com/bucket/delta/invoices", "s3://bucket/delta/invoices"),
        ("https://bucket.s3.amazonaws.com/delta/my%20table", "s3://bucket/delta/my table"),
        ("s3://bucket", None),
        ("https://s3.eu-central-1.amazonaws.com/bucket", None),
        ("https://storage.googleapis.com/bucket/delta/invoices", None),
        ("http://localhost:19000/bucket/delta/invoices", None),
        ("gs://bucket/delta/invoices", None),
        ("direct://trino", None),
        ("", None),
    ],
)
def test_normalize_s3_location(location: str, expected: str | None) -> None:
    assert normalize_s3_location(location) == expected


@pytest.mark.parametrize(
    "url_pattern, expected",
    [
        ("https://bucket.s3.amazonaws.com/dlt/team_2/modeling/eu_x", "s3://bucket/dlt/team_2/modeling/eu_x"),
        ("s3://bucket/delta/invoices/_delta_log/", "s3://bucket/delta/invoices"),
        ("https://bucket.s3.amazonaws.com/events/event_date=*/x/*.parquet", None),
        ("s3://bucket/delta/{a,b}", None),
        ("s3://bucket/_delta_log", None),
    ],
)
def test_delta_table_root(url_pattern: str, expected: str | None) -> None:
    assert delta_table_root(url_pattern) == expected


@pytest.mark.parametrize(
    "statement, expected",
    [
        (
            'CREATE TABLE "ext_db__lake"."billing"."invoices" (\n   id bigint\n)\n'
            "WITH (\n   location = 's3://bucket/delta/invoices'\n)",
            "s3://bucket/delta/invoices",
        ),
        (
            "CREATE TABLE t (\n   id bigint COMMENT 'location = ''s3://other/x'''\n)\n"
            "WITH (\n   location = 's3://bucket/it''s',\n   partitioned_by = ARRAY['day']\n)",
            "s3://bucket/it's",
        ),
        ("CREATE TABLE t (\n   id bigint\n)", None),
        ("CREATE TABLE t (id bigint) WITH (location = 'file:///tmp/t')", None),
    ],
)
def test_location_from_show_create_table(statement: str, expected: str | None) -> None:
    assert location_from_show_create_table(statement) == expected
