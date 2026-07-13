/**
 * Actionable recovery hints appended to non-recoverable tool errors (5xx).
 *
 * `handleToolError` returns the raw PostHog API error verbatim. For a 5xx that
 * body is usually an opaque "Internal Server Error" that gives an agent nothing
 * to act on — it just retries the same failing call. These hints add a short,
 * endpoint-aware "here's how to recover" footer, modeled on the multi-line
 * guidance that `MissingProjectContextError` and `formatPermissionErrorMessage`
 * already give for their cases (name the next tools to call, in order).
 *
 * Matching is keyed off the failed request URL — the source of truth for what
 * actually broke — so it works in both the direct MCP tool path and the `exec`
 * path without depending on how the tool name is plumbed through.
 */

/**
 * The logs query endpoints scan ClickHouse and time out (surfacing as a 5xx)
 * when the window is too wide or the filters too loose. They all share the same
 * narrow-and-retry recovery: shrink the window, add a service/attribute filter,
 * and pre-size with the cheap count tools before pulling rows.
 */
const LOGS_QUERY_RECOVERY_HINT = [
    'This logs query failed server-side. The most common cause is a query that scans too much data and times out — not a bug in your filters.',
    '',
    'Narrow the query and retry:',
    '1. Shorten `dateRange` (e.g. `-1h` instead of `-1d`).',
    '2. Add `serviceNames` — discover them with `logs-attribute-values-list { key: "service.name", attribute_type: "resource" }` (or `logs-services`) — or add a `log_resource_attribute` filter to `filterGroup`.',
    '3. Size the volume first with `logs-count`, then locate the busy window with `logs-count-ranges` (each returned bucket carries a `date_from`/`date_to` you can feed back as the next `dateRange`), and only then call `query-logs`.',
    '',
    'Many cheap count calls beat one broad `query-logs`.',
].join('\n')

/** URL path fragments for the logs endpoints that share the recovery above. */
const LOGS_QUERY_URL_FRAGMENTS = [
    '/logs/query/',
    '/logs/count/',
    '/logs/count-ranges/',
    '/logs/services/',
    '/logs/sparkline/',
]

interface RecoveryHintInput {
    /** The failed request URL (from `PostHogApiError.url`), if the error was an HTTP failure. */
    url?: string | undefined
    /** The HTTP status code, if known. */
    status?: number | undefined
}

/**
 * Returns an actionable recovery hint for a failed tool call, or `undefined`
 * when none applies.
 *
 * Only fires for server-side failures (5xx) or non-HTTP errors with no status —
 * 4xx responses already carry an actionable validation detail and must not be
 * buried under a generic hint.
 */
export function getToolRecoveryHint({ url, status }: RecoveryHintInput): string | undefined {
    // 4xx is recoverable agent input, already surfaced verbatim upstream.
    if (status !== undefined && status < 500) {
        return undefined
    }
    if (url && LOGS_QUERY_URL_FRAGMENTS.some((fragment) => url.includes(fragment))) {
        return LOGS_QUERY_RECOVERY_HINT
    }
    return undefined
}
