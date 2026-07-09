import os
import json
import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Literal, Optional
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlparse, urlunparse

from django.conf import settings

import structlog
import posthoganalytics
from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)
from prometheus_client import Counter, Histogram

from posthog.schema import FunnelLayout, NodeKind

from posthog.hogql.errors import AccessDeniedError

from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.event_usage import AnalyticsProps, EventSource
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.security.url_validation import is_url_allowed
from posthog.tasks.exporter import EXPORT_TIMER
from posthog.utils import absolute_uri

from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.exports.backend.models.exported_asset import ExportedAsset, get_render_access_token, save_content
from products.exports.backend.tasks.exporter_utils import log_error_if_site_url_not_reachable
from products.exports.backend.tasks.failure_handler import (
    BrowserlessUnavailable,
    InvalidExportContext,
    classify_failure_type,
)
from products.product_analytics.backend.api.insight_variable import map_stale_to_latest
from products.product_analytics.backend.models.insight_variable import InsightVariable

if TYPE_CHECKING:
    from posthog.caching.fetch_from_cache import InsightResult
    from posthog.models import Team, User

    from products.dashboards.backend.models.dashboard import Dashboard
    from products.product_analytics.backend.models.insight import Insight

logger = structlog.get_logger(__name__)

IMAGE_EXPORT_RENDER_DURATION = Histogram(
    "image_export_render_duration_seconds",
    "Image export render time (browser navigate + wait + screenshot), by backend and outcome",
    labelnames=["backend", "outcome"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 45, 60, 90, 120, float("inf")),
)
IMAGE_EXPORT_RENDER_FAILURE_COUNTER = Counter(
    "image_export_render_failure_total",
    "Image export render failures by backend and classified failure type",
    labelnames=["backend", "failure_type"],
)


def _build_cache_keys_param(insight_cache_keys: Optional[dict[int, str]]) -> str:
    if not insight_cache_keys:
        return ""
    return f"&cache_keys={quote(json.dumps(insight_cache_keys))}"


TMP_DIR = "/tmp"  # NOTE: Externalise this to ENV var

MAX_WIDTH_PIXELS = 4000  # Max width for wide content like funnels with many steps
MAX_HEIGHT_PIXELS = 5000  # Prevents Chrome from consuming excessive memory on very tall pages
CONTENT_PADDING = 80  # Padding for card borders

MEASURE_CONTENT_HEIGHT_JS = """
    const element = document.querySelector('.InsightCard__viz') ||
                  document.querySelector('.ExportedInsight__content') ||
                  document.querySelector('.replayer-wrapper') ||
                  document.querySelector('.heatmap-exporter');
    if (element) {
        const rect = element.getBoundingClientRect();
        return Math.max(rect.height, document.body.scrollHeight);
    }
    return document.body.scrollHeight;
"""

MEASURE_CONTENT_WIDTH_JS = f"""
            // Check for heatmap exporter first — its width is set explicitly
            const heatmapElement = document.querySelector('.heatmap-exporter');
            if (heatmapElement) {{
                return heatmapElement.offsetWidth;
            }}

            // Check for replay player
            const replayElement = document.querySelector('.replayer-wrapper');
            if (replayElement) {{
                return replayElement.offsetWidth;
            }}

            // Left-to-right funnel (FunnelStepsBarChart, quill-charts). The bars + legend carry an
            // explicit pixel width on this element, while every ancestor stretches to fill the wide
            // export viewport — so measure this element directly rather than the stretched wrapper.
            const funnelStepsCanvas = document.querySelector('[data-attr="funnel-steps-bar-chart-canvas"]');
            if (funnelStepsCanvas) {{
                return Math.ceil(funnelStepsCanvas.getBoundingClientRect().width) + {CONTENT_PADDING};
            }}

            // Legacy left-to-right funnel (FunnelBarVertical, table-based)
            // Top-to-bottom funnels use FunnelBarHorizontal and don't need width expansion
            const funnelElement = document.querySelector('.FunnelBarVertical');
            if (funnelElement) {{
                // Force funnel to shrink to content size
                funnelElement.style.width = 'fit-content';
                funnelElement.style.maxWidth = 'fit-content';

                const table = funnelElement.querySelector('table');
                if (table) {{
                    table.style.width = 'fit-content';
                    table.style.maxWidth = 'fit-content';
                }}

                // Force a reflow
                void funnelElement.offsetWidth;

                // Now measure the actual content width
                return funnelElement.offsetWidth + {CONTENT_PADDING};
            }}

            // Fall back to table width for insights
            const tableElement = document.querySelector('table');
            if (tableElement) {{
                return tableElement.offsetWidth * 1.5;
            }}

            return null;
        """

ScreenWidth = Literal[800, 1920, 1400, 4000]
CSSSelector = Literal[".InsightCard", ".ExportedInsight", ".replayer-wrapper", ".heatmap-exporter"]


def _export_to_png(
    exported_asset: ExportedAsset,
    max_height_pixels: Optional[int] = None,
    insight_cache_keys: Optional[dict[int, str]] = None,
) -> None:
    """
    Exporting an Insight means:
    1. Loading the Insight from the web app in a dedicated rendering mode
    2. Waiting for the page to have fully loaded before taking a screenshot to disk
    3. Loading that screenshot into memory and saving the data representation to the relevant Insight
    4. Cleanup: Remove the old file and close the browser session

    Args:
        exported_asset: The asset to export
        max_height_pixels: Maximum height for the screenshot
        insight_cache_keys: Map of insight IDs to their cache keys, used to ensure
            the exporter fetches data from the exact cache that was warmed
    """
    image_path = None

    try:
        if not settings.SITE_URL:
            raise Exception(
                "The SITE_URL is not set. The exporter must have HTTP access to the web app in order to work"
            )

        if not settings.BROWSERLESS_CDP_URL:
            raise Exception(
                "BROWSERLESS_CDP_URL is not set. Image exports render via a browserless service and "
                "cannot run without one configured"
            )

        image_id = str(uuid.uuid4())
        image_path = os.path.join(TMP_DIR, f"{image_id}.png")

        if not os.path.exists(TMP_DIR):
            os.makedirs(TMP_DIR)

        access_token = get_render_access_token(exported_asset, timedelta(minutes=15))

        screenshot_width: ScreenWidth
        wait_for_css_selector: CSSSelector
        screenshot_height: int = 600
        page_load_timeout: int = 40
        if exported_asset.insight is not None:
            show_legend = exported_asset.insight.show_legend
            legend_param = "&legend=true" if show_legend else ""
            cache_keys_param = _build_cache_keys_param(insight_cache_keys)
            url_to_render = absolute_uri(f"/exporter?token={access_token}{legend_param}{cache_keys_param}")
            wait_for_css_selector = ".ExportedInsight"
            query = exported_asset.insight.query or {}
            source = query.get("source", query)  # This to handle the InsightVizNode wrapper
            is_funnel = source.get("kind") == NodeKind.FUNNELS_QUERY
            # Only use wide width for left-to-right funnels (vertical layout, which is the default)
            # Top-to-bottom funnels (horizontal layout) grow vertically, not horizontally
            funnels_filter = source.get("funnelsFilter") or {}
            funnel_layout = funnels_filter.get("layout")
            is_left_to_right_funnel = is_funnel and (funnel_layout is None or funnel_layout == FunnelLayout.VERTICAL)
            # Set initial window size large enough for wide content like left-to-right funnels with many steps
            # Small funnels will be constrained later.
            # The higher the number, the more RAM will be required by the Chromium driver.
            screenshot_width = 4000 if is_left_to_right_funnel else 800
        elif exported_asset.dashboard is not None:
            cache_keys_param = _build_cache_keys_param(insight_cache_keys)
            url_to_render = absolute_uri(f"/exporter?token={access_token}{cache_keys_param}")
            wait_for_css_selector = ".InsightCard"
            screenshot_width = 1920
        elif exported_asset.export_context and exported_asset.export_context.get("session_recording_id"):
            # Handle replay export using /exporter route (same as insights/dashboards)
            url_to_render = absolute_uri(
                f"/exporter?token={access_token}&t={exported_asset.export_context.get('timestamp') or 0}&fullscreen=true"
            )
            wait_for_css_selector = exported_asset.export_context.get("css_selector", ".replayer-wrapper")
            screenshot_width = exported_asset.export_context.get("width", 1400)
            screenshot_height = exported_asset.export_context.get("height", 600)

            logger.info(
                "exporting_replay",
                session_recording_id=exported_asset.export_context.get("session_recording_id"),
                timestamp=exported_asset.export_context.get("timestamp"),
                url_to_render=url_to_render,
                css_selector=wait_for_css_selector,
                token_preview=access_token[:10],
            )
        elif exported_asset.export_context and exported_asset.export_context.get("heatmap_url"):
            heatmap_url = exported_asset.export_context["heatmap_url"]
            ok, err = is_url_allowed(heatmap_url)
            if not ok:
                raise Exception(f"heatmap_url blocked by SSRF protection: {err}")

            # URL-encode the page and data URLs so their inner `?` and `&` (e.g.
            # `?width=1024&format=jpeg` on screenshot content URLs) don't corrupt
            # the `/exporter` query string.
            encoded_page_url = quote(heatmap_url, safe="")
            encoded_data_url = quote(exported_asset.export_context.get("heatmap_data_url") or "", safe="")
            url_to_render = absolute_uri(
                f"/exporter?token={access_token}&pageURL={encoded_page_url}&dataURL={encoded_data_url}"
            )
            wait_for_css_selector = exported_asset.export_context.get("css_selector", ".heatmaps-ready")
            screenshot_width = exported_asset.export_context.get("width", 1400)
            screenshot_height = exported_asset.export_context.get("height", 600)
            # Heatmaps wait for the data fetch to complete (`.heatmaps-ready` is added
            # by HeatmapCanvas after heatmapDataLogic loads the data), which can take a while.
            page_load_timeout = 100

            logger.info(
                "exporting_heatmap",
                heatmap_url=exported_asset.export_context.get("heatmap_url"),
                url_to_render=url_to_render,
                css_selector=wait_for_css_selector,
                token_preview=access_token[:10],
            )
        else:
            raise InvalidExportContext(
                "Export is missing required dashboard, insight ID, or session_recording_id in export_context"
            )

        logger.info("exporting_asset", asset_id=exported_asset.id, render_url=url_to_render)

        render_start = time.perf_counter()
        try:
            _screenshot_asset_browserless(
                image_path,
                url_to_render,
                screenshot_width,
                wait_for_css_selector,
                screenshot_height,
                max_height_pixels,
                page_load_timeout,
            )
        except Exception as e:
            IMAGE_EXPORT_RENDER_DURATION.labels(backend="browserless", outcome="failure").observe(
                time.perf_counter() - render_start
            )
            IMAGE_EXPORT_RENDER_FAILURE_COUNTER.labels(
                backend="browserless", failure_type=classify_failure_type(e)
            ).inc()
            raise
        IMAGE_EXPORT_RENDER_DURATION.labels(backend="browserless", outcome="success").observe(
            time.perf_counter() - render_start
        )

        with open(image_path, "rb") as image_file:
            image_data = image_file.read()

        save_content(exported_asset, image_data)

        os.remove(image_path)

    except Exception:
        # Ensure we clean up the tmp file in case anything went wrong
        if image_path and os.path.exists(image_path):
            os.remove(image_path)

        log_error_if_site_url_not_reachable()

        raise


def _build_cdp_endpoint(cdp_url: str, token: str, session_timeout_ms: int) -> str:
    parsed = urlparse(cdp_url)
    query = {
        key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key not in ("token", "timeout")
    }
    if token:
        query["token"] = token
    query["timeout"] = str(session_timeout_ms)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _redact_browserless_token(message: str) -> str:
    token = settings.BROWSERLESS_TOKEN
    if not token:
        return message
    return message.replace(token, "***").replace(quote_plus(token), "***")


def _effective_max_height(max_height_pixels: Optional[int]) -> int:
    return min(max_height_pixels, MAX_HEIGHT_PIXELS) if max_height_pixels else MAX_HEIGHT_PIXELS


def _cap_height(raw_height: int, effective_max: int, url: str, *, final: bool = False) -> int:
    if raw_height <= effective_max:
        return raw_height
    if final:
        logger.warning(
            "screenshot_final_height_capped",
            original_final_height=raw_height,
            capped_height=effective_max,
            url=url,
        )
    else:
        logger.warning(
            "screenshot_height_capped",
            original_height=raw_height,
            capped_height=effective_max,
            url=url,
        )
    return effective_max


def _resolve_width(raw_width: object, screenshot_width: int, url: str) -> int:
    if not isinstance(raw_width, (int, float)):
        return screenshot_width
    calculated_width = raw_width or screenshot_width
    if calculated_width > MAX_WIDTH_PIXELS:
        logger.warning(
            "screenshot_width_capped",
            original_width=calculated_width,
            capped_width=MAX_WIDTH_PIXELS,
            url=url,
        )
    return min(MAX_WIDTH_PIXELS, int(calculated_width))


_BROWSERLESS_CONNECTION_ERROR_INDICATORS = (
    "target closed",
    "has been closed",
    "connection closed",
    "websocket",
    "disconnected",
    "econnrefused",
)


def _is_browserless_connection_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(indicator in message for indicator in _BROWSERLESS_CONNECTION_ERROR_INDICATORS)


def _save_debug_screenshot(take_screenshot: Callable[[str], object], image_path: str) -> None:
    try:
        take_screenshot(image_path)
        posthoganalytics.tag("image_path", image_path)
    except Exception:
        pass


def _screenshot_asset_browserless(
    image_path: str,
    url_to_render: str,
    screenshot_width: ScreenWidth,
    wait_for_css_selector: CSSSelector,
    screenshot_height: int = 600,
    max_height_pixels: Optional[int] = None,
    page_load_timeout: int = 40,
) -> None:
    endpoint = _build_cdp_endpoint(
        settings.BROWSERLESS_CDP_URL, settings.BROWSERLESS_TOKEN, settings.BROWSERLESS_SESSION_TIMEOUT_MS
    )

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(endpoint, timeout=settings.BROWSERLESS_CONNECT_TIMEOUT_MS)
        except (PlaywrightError, PlaywrightTimeoutError) as e:
            raise BrowserlessUnavailable(
                f"Failed to connect to browserless: {_redact_browserless_token(str(e))}"
            ) from None

        disconnected = [False]
        browser.on("disconnected", lambda *_: disconnected.__setitem__(0, True))

        context = None
        page = None
        try:
            context = browser.new_context(
                device_scale_factor=2,
                viewport={"width": screenshot_width, "height": screenshot_height},
            )
            page = context.new_page()
            posthoganalytics.tag("url_to_render", url_to_render)

            try:
                page.goto(url_to_render, wait_until="domcontentloaded", timeout=page_load_timeout * 1000)
                page.wait_for_selector(wait_for_css_selector, state="attached", timeout=page_load_timeout * 1000)
            except PlaywrightTimeoutError as e:
                with posthoganalytics.new_context():
                    posthoganalytics.tag("stage", "image_exporter.page_load_timeout")
                    _save_debug_screenshot(lambda p: page.screenshot(path=p), image_path)
                    capture_exception(e)

                raise PlaywrightTimeoutError("Timeout while waiting for the page to load") from e

            try:
                page.wait_for_selector(".Spinner", state="detached", timeout=20000)
            except PlaywrightTimeoutError as e:
                with posthoganalytics.new_context():
                    posthoganalytics.tag("stage", "image_exporter.wait_for_spinner_timeout")
                    _save_debug_screenshot(lambda p: page.screenshot(path=p), image_path)
                    capture_exception(e)

            effective_max = _effective_max_height(max_height_pixels)
            height = _cap_height(
                int(page.evaluate(f"() => {{ {MEASURE_CONTENT_HEIGHT_JS} }}")), effective_max, url_to_render
            )
            width = _resolve_width(
                page.evaluate(f"() => {{ {MEASURE_CONTENT_WIDTH_JS} }}"), screenshot_width, url_to_render
            )

            page.set_viewport_size({"width": width, "height": height})

            page.wait_for_timeout(500)

            final_height = _cap_height(
                int(page.evaluate(f"() => {{ {MEASURE_CONTENT_HEIGHT_JS} }}")), effective_max, url_to_render, final=True
            )

            page.set_viewport_size({"width": width, "height": final_height})
            page.screenshot(path=image_path)
        except BrowserlessUnavailable:
            raise
        except PlaywrightTimeoutError:
            raise
        except PlaywrightError as e:
            if disconnected[0] or _is_browserless_connection_error(e):
                raise BrowserlessUnavailable(_redact_browserless_token(str(e))) from None

            with posthoganalytics.new_context():
                posthoganalytics.tag("url_to_render", url_to_render)
                if page:
                    _save_debug_screenshot(lambda p: page.screenshot(path=p), image_path)
            capture_exception(e)

            raise
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            try:
                browser.close()
            except Exception:
                pass


def _warm_insight_cache(
    insight: "Insight",
    *,
    team: "Team",
    dashboard: Optional["Dashboard"],
    user: Optional["User"],
    variables_override: Optional[dict],
    tile_filters_override: Optional[dict],
    query_override: Optional[dict],
    analytics_props: AnalyticsProps,
) -> Optional[str]:
    """Warm the query cache for one insight under the export owner's access.

    Returns the cache key so the browser render can hit the exact warmed entry. Returns None when
    the export owner can't read a table or view the insight references: rather than fail the whole
    export into error tracking, we skip warming so that one tile degrades to its access-denied state
    in the render while the rest of the export succeeds.
    """

    use_override = bool(query_override)

    def _calculate() -> "InsightResult":
        return calculate_for_query_based_insight(
            insight,
            team=team,
            dashboard=dashboard,
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            # Background render (no request user); attribute the read to the export owner.
            user=user,
            variables_override=variables_override,
            tile_filters_override=tile_filters_override,
            query_override=query_override if use_override else None,
            analytics_props=analytics_props,
        )

    try:
        if use_override:
            # query_override is upgraded inside calculate_for_query_based_insight, so we skip
            # upgrade_query (which only upgrades insight.query we won't use).
            result = _calculate()
        else:
            with upgrade_query(insight):
                result = _calculate()
    except AccessDeniedError:
        logger.warning(
            "export_image.insight_access_denied",
            insight_id=insight.id,
            dashboard_id=dashboard.id if dashboard else None,
        )
        return None

    return result.cache_key or None


def export_image(
    exported_asset: ExportedAsset, max_height_pixels: Optional[int] = None, source: Optional[EventSource] = None
) -> None:
    with posthoganalytics.new_context():
        posthoganalytics.tag("team_id", exported_asset.team_id if exported_asset else "unknown")
        posthoganalytics.tag("asset_id", exported_asset.id if exported_asset else "unknown")

        try:
            # Track cache keys for insights so we can pass them to Chrome for guaranteed cache hits
            insight_cache_keys: dict[int, str] = {}
            export_analytics_props: AnalyticsProps = {"source": source or EventSource.EXPORT}

            if exported_asset.insight:
                logger.info(
                    "export_image.calculate_insight",
                    insight_id=exported_asset.insight.id,
                    dashboard_id=exported_asset.dashboard.id if exported_asset.dashboard else None,
                )

                # When export_context contains a source query, use it as the query for cache warming.
                # This captures the user's full current state (variables, filters, date ranges, etc.).
                # Falls back to the saved insight query for subscriptions and other server-initiated exports.
                export_context = exported_asset.export_context or {}
                query_override = export_context.get("source")

                dashboard_variables = None
                tile_filters_override = None
                if exported_asset.dashboard:
                    if exported_asset.dashboard.variables:
                        variables = list(InsightVariable.objects.filter(team=exported_asset.team).all())
                        dashboard_variables = map_stale_to_latest(exported_asset.dashboard.variables, variables)
                    tile = DashboardTile.objects.filter(
                        dashboard=exported_asset.dashboard,
                        insight=exported_asset.insight,
                    ).first()
                    if tile:
                        tile_filters_override = tile.filters_overrides

                # When query_override is set, variables_override is None because query_override
                # already encodes the user's full current state — applying saved dashboard
                # variables on top would clobber unsaved variable selections.
                cache_key = _warm_insight_cache(
                    exported_asset.insight,
                    team=exported_asset.team,
                    dashboard=exported_asset.dashboard,
                    user=exported_asset.created_by,
                    variables_override=None if query_override else dashboard_variables,
                    tile_filters_override=tile_filters_override,
                    query_override=query_override,
                    analytics_props=export_analytics_props,
                )
                if cache_key:
                    insight_cache_keys[exported_asset.insight.id] = cache_key
            elif exported_asset.dashboard:
                logger.info(
                    "export_image.calculate_dashboard_insights",
                    dashboard_id=exported_asset.dashboard.id,
                )
                # Use variable overrides from export_context (user's current unsaved selection),
                # falling back to saved dashboard variables
                export_context = exported_asset.export_context or {}
                dashboard_variables = export_context.get("variables_override")
                if not dashboard_variables and exported_asset.dashboard.variables:
                    variables = list(InsightVariable.objects.filter(team=exported_asset.team).all())
                    dashboard_variables = map_stale_to_latest(exported_asset.dashboard.variables, variables)

                tiles = (
                    exported_asset.dashboard.tiles.select_related("insight")
                    .filter(insight__isnull=False, insight__deleted=False)
                    .all()
                )
                for tile in tiles:
                    insight = tile.insight
                    if not insight or not insight.query:
                        continue

                    cache_key = _warm_insight_cache(
                        insight,
                        team=exported_asset.team,
                        dashboard=exported_asset.dashboard,
                        user=exported_asset.created_by,
                        variables_override=dashboard_variables,
                        tile_filters_override=tile.filters_overrides,
                        query_override=None,
                        analytics_props=export_analytics_props,
                    )
                    if cache_key:
                        insight_cache_keys[insight.id] = cache_key

            if exported_asset.export_format == "image/png":
                with EXPORT_TIMER.labels(type=exported_asset.export_format).time():
                    _export_to_png(
                        exported_asset,
                        max_height_pixels=max_height_pixels,
                        insight_cache_keys=insight_cache_keys or None,
                    )
            else:
                raise NotImplementedError(
                    f"Export to format {exported_asset.export_format} is not supported for insights"
                )
        except Exception as e:
            team_id = str(exported_asset.team.id) if exported_asset else "unknown"
            capture_exception(e, additional_properties={"task": "image_export", "team_id": team_id})
            logger.error("image_exporter.failed", exception=e, exc_info=True)
            raise
