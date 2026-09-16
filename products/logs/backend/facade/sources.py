"""Facade re-exports for cloud provider log sources.

The sources viewset is a ModelViewSet over ``LogsSource``, so it needs the model class
itself for its serializer and queryset. The Firehose constants come through here too so
the setup-instructions endpoint and the CloudFormation template stay in step.
"""

from products.logs.backend.cloud_sources.aws_firehose import (
    AWS_REGION_RE,
    FIREHOSE_BUFFER_INTERVAL_SECONDS,
    FIREHOSE_BUFFER_SIZE_MB,
    FIREHOSE_ENDPOINT_PATH,
    FIREHOSE_RETRY_DURATION_SECONDS,
    quick_create_url,
)
from products.logs.backend.models import LogsSource, LogsSourceProvider

__all__ = [
    "AWS_REGION_RE",
    "FIREHOSE_BUFFER_INTERVAL_SECONDS",
    "FIREHOSE_BUFFER_SIZE_MB",
    "FIREHOSE_ENDPOINT_PATH",
    "FIREHOSE_RETRY_DURATION_SECONDS",
    "LogsSource",
    "LogsSourceProvider",
    "quick_create_url",
]
