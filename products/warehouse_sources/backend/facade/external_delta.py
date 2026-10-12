from __future__ import annotations

import re
import json
import hashlib
from collections.abc import Sequence
from typing import cast
from urllib.parse import unquote, urlsplit
from uuid import UUID

from django.conf import settings

import boto3

from products.warehouse_sources.backend.facade.contracts import ExternalDeltaTable
from products.warehouse_sources.backend.models.table import DataWarehouseTable


def normalize_delta_s3_uri(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port:
        raise ValueError("Delta registration requires an unqualified S3 table location")
    path = unquote(parsed.path).rstrip("/")
    if path.endswith("/*.parquet"):
        path = path.removesuffix("/*.parquet")
    if parsed.scheme == "s3":
        bucket = parsed.netloc
    elif parsed.scheme == "https":
        match = re.fullmatch(r"([a-z0-9.-]+)\.s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com", parsed.netloc)
        if match is None:
            raise ValueError("Delta registration supports S3 and AWS S3 HTTPS locations")
        bucket = match.group(1)
    else:
        raise ValueError("Delta registration supports S3 and AWS S3 HTTPS locations")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
        raise ValueError("Invalid S3 bucket name")
    if not path or any(character in path for character in "*?{}[]") or ".." in path.split("/"):
        raise ValueError("Delta registration requires a table root without wildcards")
    return f"s3://{bucket}{path}"


def _describe_external_delta_table(table: DataWarehouseTable) -> ExternalDeltaTable:
    if table.format not in ("Delta", "DeltaS3Wrapper") or table.created_via == table.CreatedVia.MATERIALIZED_VIEW:
        raise ValueError("Only manually linked Delta tables can be registered")
    uri = normalize_delta_s3_uri(table.url_pattern)
    fingerprint = hashlib.sha256(
        json.dumps([uri, table.format, str(table.credential_id)], separators=(",", ":")).encode()
    ).hexdigest()
    return ExternalDeltaTable(id=table.id, name=table.name, uri=uri, fingerprint=fingerprint)


def list_external_delta_tables(team_id: int, table_ids: Sequence[UUID]) -> dict[UUID, ExternalDeltaTable]:
    result: dict[UUID, ExternalDeltaTable] = {}
    tables = DataWarehouseTable.raw_objects.filter(
        team_id=team_id, id__in=table_ids, deleted=False, external_data_source__isnull=True
    ).only("id", "name", "format", "url_pattern", "credential_id", "created_via")
    for table in tables:
        try:
            result[table.id] = _describe_external_delta_table(table)
        except ValueError:
            continue
    return result


def get_external_delta_table(team_id: int, table_id: UUID, *, with_credentials: bool = False) -> ExternalDeltaTable:
    tables = DataWarehouseTable.raw_objects.all()
    if with_credentials:
        tables = tables.select_related("credential")
    else:
        tables = tables.only("id", "name", "format", "url_pattern", "credential_id", "created_via")
    try:
        table = tables.get(id=table_id, team_id=team_id, deleted=False, external_data_source__isnull=True)
    except DataWarehouseTable.DoesNotExist as error:
        raise ValueError("The external table does not exist in this project") from error
    source = _describe_external_delta_table(table)
    if with_credentials and table.credential is not None and table.credential.team_id != team_id:
        raise ValueError("The table credential belongs to a different project")
    storage_options: dict[str, str] = {}
    if with_credentials and table.credential is not None:
        storage_options = {
            "AWS_ACCESS_KEY_ID": table.credential.access_key,
            "AWS_SECRET_ACCESS_KEY": table.credential.access_secret,
        }
    if with_credentials and not settings.USE_LOCAL_SETUP:
        client = boto3.client(
            "s3",
            aws_access_key_id=storage_options.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=storage_options.get("AWS_SECRET_ACCESS_KEY"),
        )
        region = cast(str | None, client.get_bucket_location(Bucket=urlsplit(source.uri).netloc)["LocationConstraint"])
        storage_options["AWS_REGION"] = "eu-west-1" if region == "EU" else (region or "us-east-1")
    return ExternalDeltaTable(
        id=table.id,
        name=table.name,
        uri=source.uri,
        fingerprint=source.fingerprint,
        storage_options=storage_options,
    )
