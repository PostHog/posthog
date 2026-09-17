import re

from posthog.api.snuffle_proxy import SnuffleProxyViewSet

_LABEL_NAME = r"[A-Za-z_][A-Za-z0-9_]*"


class LokiQueryViewSet(SnuffleProxyViewSet):
    """Loki-compatible LogQL query API over the team's logs.

    Mounted at ``/api/projects/:id/logs/loki/api/v1/...`` so a Loki client pointed at
    ``/api/projects/:id/logs`` works unchanged. Read-only: ``push`` is not exposed.
    """

    scope_object = "logs"
    upstream_prefix = "/loki/api/v1"
    allowed_paths = (
        re.compile(r"query"),
        re.compile(r"query_range"),
        re.compile(r"labels"),
        re.compile(rf"label/{_LABEL_NAME}/values"),
        re.compile(r"series"),
        re.compile(r"index/stats"),
        re.compile(r"status/buildinfo"),
    )
