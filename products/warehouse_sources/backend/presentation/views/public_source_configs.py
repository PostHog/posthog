import functools

from django.conf import settings
from django.core.cache import cache

import structlog
from drf_spectacular.utils import extend_schema
from opentelemetry import trace
from rest_framework import permissions, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.git import get_git_commit_full

from products.warehouse_sources.backend.facade.source_config import SourceConfigMapResponse
from products.warehouse_sources.backend.facade.source_management import SourceRegistry, cdc_engine

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


@functools.cache
def build_source_configs(*, include_tables: bool = True) -> dict[str, dict]:
    """Build the source-config catalog returned by both the public endpoint and the wizard.

    Each entry is the source's ``SourceConfig`` augmented with ``supportsColumnSelection`` and,
    when ``include_tables`` is set, a credential-free ``tables`` catalog (empty for SQL/file
    sources with user-defined schemas). ``tables`` exists for the posthog.com docs build; the
    in-app wizard skips it because nothing in the app reads it and it is ~40% of the payload.
    Kept in one place so the two endpoints can never drift (see ``test_matches_wizard_response``).

    The catalog is deploy-static (it only changes when source code ships), so the result is
    memoized per process and shared across processes of the same commit through the cache.
    Callers must treat it as read-only.
    """
    # A cold build imports every source module and takes seconds. Web processes restart often,
    # so processes of one commit share one build instead of each process paying for it.
    shared_key = _shared_cache_key(include_tables)
    if shared_key is not None:
        try:
            cached = cache.get(shared_key)
        except Exception:
            logger.warning("build_source_configs: shared cache read failed", exc_info=True)
            cached = None
        if cached is not None:
            return cached
    results = _build_source_configs(include_tables=include_tables)
    if shared_key is not None:
        try:
            cache.set(shared_key, results, timeout=_SHARED_CACHE_TTL_SECONDS)
        except Exception:
            logger.warning("build_source_configs: shared cache write failed", exc_info=True)
    return results


_SHARED_CACHE_TTL_SECONDS = 60 * 60 * 24


def _shared_cache_key(include_tables: bool) -> str | None:
    commit = get_git_commit_full()
    # In local dev the commit does not change when source code is edited.
    if commit is None or settings.DEBUG:
        return None
    return f"warehouse_sources:source_configs:v1:{commit}:{int(include_tables)}"


def _build_source_configs(*, include_tables: bool) -> dict[str, dict]:
    with tracer.start_as_current_span("warehouse_sources.catalog.registry"):
        sources = SourceRegistry.get_all_sources()

    results: dict[str, dict] = {}
    with tracer.start_as_current_span("warehouse_sources.catalog.build") as span:
        span.set_attribute("include_tables", include_tables)
        span.set_attribute("source_count", len(sources))
        for source_type, source in sources.items():
            if not source.listed_in_catalog:
                continue
            config = source.get_source_config.model_dump()
            config["supportsColumnSelection"] = bool(source.supports_column_selection)
            config["versions"] = list(source.supported_versions)
            config["defaultVersion"] = source.default_version
            config["apiDocsUrl"] = source.api_docs_url
            config["cdcEngine"] = cdc_engine(source_type)
            config["deprecatedVersions"] = [
                {"version": d.version, "sunsetAt": d.sunset_at.isoformat() if d.sunset_at else None}
                for d in source.deprecated_versions
            ]
            if include_tables:
                # Per-source guard: a single misbehaving source must never break the whole catalog.
                try:
                    config["tables"] = source.get_documented_tables()
                except Exception:
                    logger.exception("build_source_configs: get_documented_tables failed", source_type=str(source_type))
                    config["tables"] = []
            results[str(source_type)] = config

    return results


class PublicSourceConfigViewSet(viewsets.ViewSet):
    """
    Public (unauthenticated) endpoint that returns the full SourceConfig
    for every registered data warehouse import source — including the
    input field schemas needed to render setup forms and, for fixed-schema
    sources, the documented table catalog rendered on posthog.com docs.

    This is the data-warehouse equivalent of ``/api/public_hog_function_templates``.
    """

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        responses={200: SourceConfigMapResponse},
        description=(
            "Returns a map of source type identifiers to their full SourceConfig. Each entry is "
            "augmented with `supportsColumnSelection`, a `tables` array (the credential-free "
            "documented table catalog; empty for SQL/file sources with user-defined schemas), and "
            "vendor API version metadata: `versions` (supported version labels), `defaultVersion`, "
            "`apiDocsUrl` (vendor API docs/changelog URL or null), and `deprecatedVersions` "
            "(array of `{version, sunsetAt}` with `sunsetAt` an ISO date or null), and `cdcEngine` "
            "(the change data capture engine, or null when the source has no CDC)."
        ),
    )
    def list(self, request: Request) -> Response:
        # Results are deploy-static (they only change when source code ships), so this is a
        # safe candidate for caching if the endpoint ever gets hot; today it is fetched only
        # at posthog.com build time.
        return Response(status=status.HTTP_200_OK, data=build_source_configs())
