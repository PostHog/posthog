from typing import Any

import pytest

from django.test import override_settings

from products.warehouse_sources.backend.file_uploads import (
    InvalidUploadError,
    LegacyUpload,
    UploadLocation,
    parse_hosted_upload,
    sanitize_upload_filename,
)

UPLOAD_ID = "11111111-2222-4333-8444-555555555555"
DOMAIN = "warehouse.example.com"
BUCKET = "ph-warehouse"


@override_settings(DATAWAREHOUSE_BUCKET=BUCKET, DATAWAREHOUSE_BUCKET_DOMAIN=DOMAIN)
def test_an_upload_location_is_built_inside_the_team_folder() -> None:
    location = UploadLocation(team_id=7, upload_id=UPLOAD_ID, filename="orders.csv")

    assert location.key == f"file_uploads/team_7/{UPLOAD_ID}/orders.csv"
    assert location.path == f"{BUCKET}/file_uploads/team_7/{UPLOAD_ID}/orders.csv"
    assert location.url_pattern == f"https://{DOMAIN}/file_uploads/team_7/{UPLOAD_ID}/orders.csv"
    assert LegacyUpload(team_id=7, filename="orders.csv").path == f"{BUCKET}/managed/team_7/orders.csv"


@pytest.mark.parametrize(
    "team_id, upload_id, filename",
    [
        # Upload ids that would leave the upload folder, or name a second key for the same upload.
        (7, "../team_8/11111111-2222-4333-8444-555555555555", "orders.csv"),
        (7, "..", "orders.csv"),
        (7, "/etc", "orders.csv"),
        (7, "other-bucket/key", "orders.csv"),
        (7, "11111111-2222-4333-8444-555555555555/../..", "orders.csv"),
        (7, "11111111-2222-4333-8444-555555555555/sub", "orders.csv"),
        (7, "11111111222243338444555555555555", "orders.csv"),
        (7, "{11111111-2222-4333-8444-555555555555}", "orders.csv"),
        (7, "11111111-2222-4333-8444-55555555555A", "orders.csv"),
        (7, "", "orders.csv"),
        (7, None, "orders.csv"),
        # Filenames that are a path, hidden, empty, or carry characters a key must not hold.
        (7, UPLOAD_ID, "../../team_8/secret.csv"),
        (7, UPLOAD_ID, "../orders.csv"),
        (7, UPLOAD_ID, ".."),
        (7, UPLOAD_ID, "."),
        (7, UPLOAD_ID, ".hidden.csv"),
        (7, UPLOAD_ID, "/etc/passwd"),
        (7, UPLOAD_ID, "sub/orders.csv"),
        (7, UPLOAD_ID, "orders.csv\x00.parquet"),
        (7, UPLOAD_ID, "orders?.csv"),
        (7, UPLOAD_ID, "orders%2F.csv"),
        (7, UPLOAD_ID, "ördërs.csv"),
        (7, UPLOAD_ID, ""),
        (7, UPLOAD_ID, None),
        # The team always comes from PostHog, but a bad one still never builds a key.
        (0, UPLOAD_ID, "orders.csv"),
        (-1, UPLOAD_ID, "orders.csv"),
        (True, UPLOAD_ID, "orders.csv"),
        ("7", UPLOAD_ID, "orders.csv"),
    ],
)
def test_a_crafted_upload_never_builds_a_key(team_id: Any, upload_id: Any, filename: Any) -> None:
    with pytest.raises(InvalidUploadError):
        UploadLocation(team_id=team_id, upload_id=upload_id, filename=filename)


@pytest.mark.parametrize("filename", ["../x.csv", ".hidden", "", "a/b.csv"])
def test_a_crafted_legacy_filename_never_builds_a_key(filename: str) -> None:
    with pytest.raises(InvalidUploadError):
        LegacyUpload(team_id=7, filename=filename)


@pytest.mark.parametrize(
    "url_pattern, expected",
    [
        (
            f"https://{DOMAIN}/file_uploads/team_7/{UPLOAD_ID}/orders.csv",
            UploadLocation(team_id=7, upload_id=UPLOAD_ID, filename="orders.csv"),
        ),
        (f"https://{DOMAIN}/managed/team_7/orders.csv", LegacyUpload(team_id=7, filename="orders.csv")),
        # Another team's files, even when the requesting team's id is a prefix of it.
        (f"https://{DOMAIN}/file_uploads/team_8/{UPLOAD_ID}/orders.csv", None),
        (f"https://{DOMAIN}/file_uploads/team_77/{UPLOAD_ID}/orders.csv", None),
        (f"https://{DOMAIN}/managed/team_70/orders.csv", None),
        # Objects PostHog writes itself in the same bucket.
        (f"https://{DOMAIN}/dlt/team_7_model_abc/modeling/orders", None),
        (f"https://{DOMAIN}/data_pipelines_extract/team_7/orders.csv", None),
        # Keys that aren't exactly one upload.
        (f"https://{DOMAIN}/file_uploads/team_7/{UPLOAD_ID}/sub/orders.csv", None),
        (f"https://{DOMAIN}/file_uploads/team_7/{UPLOAD_ID}/../orders.csv", None),
        (f"https://{DOMAIN}/file_uploads/team_7/not-a-uuid/orders.csv", None),
        (f"https://{DOMAIN}/managed/team_7/sub/orders.csv", None),
        (f"https://{DOMAIN}/managed/team_7/*.csv", None),
        (f"https://{DOMAIN}/managed/team_7/", None),
        # Other hosts and schemes.
        (f"https://{DOMAIN}.evil.example/managed/team_7/orders.csv", None),
        (f"http://{DOMAIN}/managed/team_7/orders.csv", None),
        ("https://customer.s3.amazonaws.com/managed/team_7/orders.csv", None),
        ("", None),
    ],
)
@override_settings(DATAWAREHOUSE_BUCKET=BUCKET, DATAWAREHOUSE_BUCKET_DOMAIN=DOMAIN)
def test_only_the_teams_own_uploads_are_hosted_uploads(url_pattern: str, expected: object) -> None:
    assert parse_hosted_upload(7, url_pattern) == expected


@override_settings(DATAWAREHOUSE_BUCKET="", DATAWAREHOUSE_BUCKET_DOMAIN=DOMAIN)
def test_no_hosted_upload_without_a_bucket() -> None:
    assert parse_hosted_upload(7, f"https://{DOMAIN}/managed/team_7/orders.csv") is None


@pytest.mark.parametrize(
    "name, expected",
    [
        ("orders.csv", "orders.csv"),
        ("my orders (1).csv", "my_orders__1_.csv"),
        ("a/../../secret.csv", "a_.._.._secret.csv"),
        ("../../secret.csv", None),
        ("_private.csv", "_private.csv"),
        (".env", None),
        ("..", None),
        ("", None),
    ],
)
def test_sanitized_filenames_are_always_safe_upload_filenames(name: str, expected: str | None) -> None:
    sanitized = sanitize_upload_filename(name)

    assert sanitized == expected
    if sanitized is not None:
        UploadLocation(team_id=7, upload_id=UPLOAD_ID, filename=sanitized)
