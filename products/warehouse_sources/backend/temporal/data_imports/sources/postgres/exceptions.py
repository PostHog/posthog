"""Postgres source exceptions."""


class CDCHandledExternally(Exception):
    """Raised when a CDC streaming schema is encountered in source_for_pipeline.

    CDC streaming schemas are handled by CDCExtractionWorkflow, not by the
    regular ExternalDataJobWorkflow pipeline.
    """


class XminUnsupportedError(Exception):
    """Raised when an xmin sync targets a relation that can't support it.

    Deterministic (a server too old, or a partitioned parent), so the class name
    is listed in `PostgresSource.get_non_retryable_errors` to stop Temporal
    retrying into the same wall.
    """


class IncrementalFieldTypeMismatchError(Exception):
    """Raised when the stored incremental field type no longer maps to the live column type.

    The incremental field type is captured when a sync is configured and then persisted. If the
    column is later altered to an incompatible type (e.g. a timestamp column changed to text),
    `_build_query` still emits a literal of the stored type and Postgres rejects the comparison
    with "operator does not exist: text > timestamp ...", permanently halting the sync behind a
    cryptic error. Detecting the drift up front lets us fail with an actionable message. The stable
    "stored incremental field type no longer matches the column type" fragment is listed in
    `PostgresSource.get_non_retryable_errors` so the failure is non-retryable at both the raw
    activity layer and the Temporal-wrapped workflow layer.
    """


class PostHogDatabaseConnectionError(Exception):
    """Raised when loading sync metadata from PostHog's own database fails to connect.

    This is a PostHog-side infrastructure blip (e.g. a transient DNS failure resolving our
    database host), not a problem with the customer's Postgres. Its message intentionally
    avoids the connection-error substrings in `PostgresSource.get_non_retryable_errors`: a
    failure reaching our database stringifies the same as a customer misconfiguration (e.g.
    "Name or service not known"), and must stay retryable rather than be misclassified as
    non-retryable and stop a healthy sync.
    """
