"""Patterns that recognize a GitHub pull request URL stored in a text column.

They mirror `GitHubIntegrationBase.parse_pull_request_url`, so a report the inbox counts as
carrying a pull request is one the reader can parse back into a repository and a number.

Partial indexes carry these same expressions as their predicate, which is what lets Postgres
answer the inbox's pull-request filter from an index instead of matching the pattern against
every row of the team. A change here therefore needs a matching migration — `makemigrations
--check` reports the drift.
"""

PULL_REQUEST_URL_BODY = (
    r"[A-Za-z][A-Za-z0-9+.-]*://(www\.)?github\.com/+[^/?#]+/+[^/?#]+/+pull/+[+-]?[ \t\r\n\f\v]*[0-9]+"
)
PULL_REQUEST_URL_PATTERN = rf"^{PULL_REQUEST_URL_BODY}([/?#].*)?$"
PULL_REQUEST_URL_ARRAY_PATTERN = rf'"{PULL_REQUEST_URL_BODY}([/?#][^"]*)?"'
