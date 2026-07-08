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


class ForeignServerUnreachableError(Exception):
    """Raised when a setup query touched a postgres_fdw foreign table whose foreign server failed.

    postgres_fdw/dblink report a failure to connect to a *foreign* server with SQLSTATE 08001
    (`SqlclientUnableToEstablishSqlconnection`), embedding the downstream libpq error verbatim —
    e.g. "... failed: Connection refused". That English wording collides with the connect-time
    substrings in `PostgresSource.get_non_retryable_errors` (which target the *direct* connection to
    the customer's database), so a foreign server that's briefly down (failover, restart) would be
    misclassified as a permanent misconfiguration and stop a healthy sync. The server-side sibling of
    `PostHogDatabaseConnectionError`: its message intentionally avoids those substrings so a transient
    foreign-server outage stays retryable.
    """
