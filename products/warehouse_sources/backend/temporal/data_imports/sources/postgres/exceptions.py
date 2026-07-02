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


class PostHogDatabaseConnectionError(Exception):
    """Raised when loading sync metadata from PostHog's own database fails to connect.

    This is a PostHog-side infrastructure blip (e.g. a transient DNS failure resolving our
    database host), not a problem with the customer's Postgres. Its message intentionally
    avoids the connection-error substrings in `PostgresSource.get_non_retryable_errors`: a
    failure reaching our database stringifies the same as a customer misconfiguration (e.g.
    "Name or service not known"), and must stay retryable rather than be misclassified as
    non-retryable and stop a healthy sync.
    """
