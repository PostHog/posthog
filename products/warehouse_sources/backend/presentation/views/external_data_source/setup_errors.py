"""Stable error codes for the source setup, create and CDC prerequisite endpoints.

Responses keep their human-readable `message` and gain a machine-readable `code`, so clients and
analytics can group failures without parsing text. Never put a secret value in a message.
"""

from __future__ import annotations

from django.db import models

from rest_framework import status
from rest_framework.response import Response


class SourceSetupErrorCode(models.TextChoices):
    UNRESOLVED_SECRET_REF = "unresolved_secret_ref", "Unresolved secret reference"
    CREDENTIAL_NOT_FOUND = "credential_not_found", "Stored credential not found"
    CREDENTIAL_EXPIRED = "credential_expired", "Stored credential expired"
    CREDENTIAL_SOURCE_TYPE_MISMATCH = "credential_source_type_mismatch", "Stored credential is for another source type"
    RESERVED_NAME = "reserved_name", "Reserved source name"
    DIRECT_QUERY_UNSUPPORTED = "direct_query_unsupported", "Direct query not supported for this source type"
    DIRECT_QUERY_NAME_REQUIRED = "direct_query_name_required", "Direct query sources need a name"
    DUPLICATE_SOURCE = "duplicate_source", "A source of this type already exists without a prefix"
    DUPLICATE_PREFIX = "duplicate_prefix", "Prefix already used by another source of this type"
    BILLING_LIMIT_REACHED = "billing_limit_reached", "Monthly sync limit reached"
    MAX_INSTANCES_REACHED = "max_instances_reached", "Too many sources of this type"
    SOURCE_UNAVAILABLE = "source_unavailable", "Source cannot be set up this way"
    INVALID_CONFIG = "invalid_config", "Invalid source config"
    CREDENTIAL_VALIDATION_FAILED = "credential_validation_failed", "Credential validation failed"
    SCHEMA_DISCOVERY_FAILED = "schema_discovery_failed", "Table discovery failed"
    NO_TABLES_FOUND = "no_tables_found", "No tables found"
    CDC_UNSUPPORTED_SOURCE_TYPE = "cdc_unsupported_source_type", "Source type does not support CDC"
    INVALID_CDC_MANAGEMENT_MODE = "invalid_cdc_management_mode", "Invalid CDC management mode"
    HOST_NOT_ALLOWED = "host_not_allowed", "Host not allowed"
    CONNECTION_FAILED = "connection_failed", "Connection failed"


def setup_error_response(code: SourceSetupErrorCode, message: str) -> Response:
    return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": message, "code": code.value})
