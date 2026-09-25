"""The object-store boundary the pipeline's parquet staging sinks share."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from structlog.types import FilteringBoundLogger

from posthog.temporal.common.errors import NonReportableError

# AWS error codes that pyarrow's S3FileSystem puts in its OSError message when the object store
# refuses a request outright instead of failing to serve it. ACCESS_DENIED means the worker holds
# no grant on the staging prefix. PermanentRedirect means the bucket it addressed lives in another
# region, which is what a staging bucket setting that names a bucket we do not own looks like.
# Neither clears on a retry, because both describe the deployment's configuration and not the state
# of the store.
PERMANENT_OBJECT_STORE_ERRORS = ("ACCESS_DENIED", "PermanentRedirect")

# Initiating the upload is a single network call, so one blip on it costs the whole chunk. Three
# attempts spend at most 6s of backoff, which is short against a sync that runs for minutes, and
# enough for the object store to serve a request that its own SDK-level retries could not.
_STAGED_WRITE_MAX_ATTEMPTS = 3


class ObjectStoreConfigurationError(NonReportableError):
    """The object store refused a staging request for a reason that belongs to the deployment.

    A missing grant on the staging prefix, or a staging bucket setting that addresses a bucket in
    another region, fails every attempt of every run until someone changes the configuration.
    Subclassing ``NonReportableError`` keeps that known condition out of error tracking instead of
    minting an issue for each refused chunk.
    """


def is_object_store_configuration_error(error: BaseException) -> bool:
    """True when the object store refused a staging request permanently.

    The two clients the sinks use report the same refusal differently. s3fs/aiobotocore, which
    clears the staged prefixes, maps an AccessDenied response onto the builtin ``PermissionError``.
    pyarrow's ``S3FileSystem``, which writes the staged parquet, sets no errno, so the refusal
    arrives as a plain ``OSError`` that carries the AWS error code in its message.
    """
    if isinstance(error, ObjectStoreConfigurationError | PermissionError):
        return True
    return isinstance(error, OSError) and any(needle in str(error) for needle in PERMANENT_OBJECT_STORE_ERRORS)


async def aretry_staged_write(
    operation: Callable[[], Coroutine[Any, Any, None]], *, path: str, logger: FilteringBoundLogger
) -> None:
    """Run one staged parquet write, retrying a transient object-store failure with backoff.

    Pass a zero-arg callable that produces the awaitable, not the awaitable itself, so a retry can
    reissue the write.

    A refused write raises ``ObjectStoreConfigurationError`` on the first attempt, because retrying
    a grant or an endpoint that the deployment got wrong only delays the same failure. An error the
    shared classifier does not recognize is not retried either, so a defect in the pipeline still
    fails as fast as it did before.
    """
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (  # noqa: PLC0415 — keeps the heavy deltalake dep off this module's top-level import path
        is_transient_object_store_error,
    )

    attempt = 0
    while True:
        attempt += 1
        try:
            await operation()
            return
        except Exception as e:
            if is_object_store_configuration_error(e):
                raise ObjectStoreConfigurationError(f"Object store refused the staged write to {path}") from e
            if attempt >= _STAGED_WRITE_MAX_ATTEMPTS or not is_transient_object_store_error(e):
                raise
            await logger.awarning(
                f"Transient object-store error staging {path} "
                f"(attempt {attempt}/{_STAGED_WRITE_MAX_ATTEMPTS}), retrying: {e}"
            )
            await asyncio.sleep(2**attempt)
