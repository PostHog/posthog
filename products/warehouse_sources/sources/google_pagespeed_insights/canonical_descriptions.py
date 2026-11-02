from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Injected by the connector on every row (not part of the raw API response).
_INJECTED_COLUMNS = {
    "requested_url": "The URL analyzed, exactly as configured on the source (not the final resolved URL, which can drift with redirects).",
    "strategy": "The Lighthouse device profile the analysis ran under: `DESKTOP` or `MOBILE`.",
    "analysis_timestamp": "ISO 8601 UTC timestamp derived from `analysisUTCTimestamp`; used as the partition key and append cursor.",
}

# Top-level fields of the PagespeedApiPagespeedResponseV5 document.
_RESPONSE_COLUMNS = {
    "kind": "The kind of result, always `pagespeedonline#result`.",
    "id": "The final, canonicalized URL that was analyzed (after any redirects).",
    "analysisUTCTimestamp": "The UTC timestamp of when the Lighthouse analysis was run, RFC 3339.",
    "lighthouseResult": "The full Lighthouse report: category scores (performance, accessibility, best-practices, SEO), individual audits, and metrics.",
    "loadingExperience": "Chrome UX Report (CrUX) field data for this specific URL, where available (real-world Core Web Vitals).",
    "originLoadingExperience": "Chrome UX Report (CrUX) field data aggregated across the whole origin, where available.",
    "version": "The Lighthouse version used to run the analysis.",
    "captchaResult": "The captcha verification result for the request.",
}

_COLUMNS = {**_INJECTED_COLUMNS, **_RESPONSE_COLUMNS}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "pagespeed_desktop": {
        "description": "PageSpeed Insights / Lighthouse analysis under the desktop profile for a configured URL, from the Google PageSpeed Insights v5 API (runPagespeed). One row per URL per sync.",
        "docs_url": "https://developers.google.com/speed/docs/insights/v5/reference/pagespeedapi/runpagespeed",
        "columns": _COLUMNS,
    },
    "pagespeed_mobile": {
        "description": "PageSpeed Insights / Lighthouse analysis under the mobile profile for a configured URL, from the Google PageSpeed Insights v5 API (runPagespeed). One row per URL per sync.",
        "docs_url": "https://developers.google.com/speed/docs/insights/v5/reference/pagespeedapi/runpagespeed",
        "columns": _COLUMNS,
    },
}
