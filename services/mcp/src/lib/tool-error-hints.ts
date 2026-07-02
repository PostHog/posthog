/**
 * Actionable recovery hints appended to tool errors that the raw API body
 * leaves an agent stuck on.
 *
 * `handleToolError` returns the raw PostHog API error verbatim. For a 5xx that
 * body is usually an opaque "Internal Server Error"; for a not-found on an
 * exact-id lookup it's a bare "Not found." — both give an agent nothing to act
 * on, so it just retries the same failing call. These hints add a short,
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

/**
 * A 404 on the function-template *retrieve* endpoint is the exception to the
 * "4xx already carries an actionable detail" rule below: the API body is a bare
 * "Not found.", and template IDs are exact and often can't be derived from the
 * destination name (e.g. Slack is `template-slack`, but Encharge is
 * `segment-encharge-cloud-actions`). Agents guess an ID from the destination
 * name, miss, and get no signal on what a valid ID looks like. Steer them to
 * list-then-retrieve so they resolve the exact ID instead of re-guessing.
 */
const HOG_FUNCTION_TEMPLATE_NOT_FOUND_HINT = [
    'No function template has that exact ID. Template IDs are exact and often cannot be guessed from the destination name (e.g. Slack is `template-slack`, but Encharge is `segment-encharge-cloud-actions`).',
    '',
    'To find the right one:',
    '1. Call `cdp-function-templates-list` (optionally filter by `type`, e.g. `destination` or `transformation`) to see every available template and its exact `id`.',
    '2. Retry `cdp-function-templates-retrieve` with that `id` as `template_id`.',
    '',
    'If nothing matches the destination you need, PostHog may not ship a dedicated template for it — the generic `template-webhook` (HTTP) destination can usually be configured instead.',
].join('\n')

/**
 * Matches a function-template *retrieve* URL — a non-empty id segment after the
 * `/hog_function_templates/` collection. The list URL (no id segment) does not
 * match, so a hint only fires for a genuine id miss.
 */
const HOG_FUNCTION_TEMPLATE_RETRIEVE_URL = /\/hog_function_templates\/[^/?]+\/?(?:$|\?)/

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
 * Fires for server-side failures (5xx) and non-HTTP errors with no status. The
 * one 4xx it fires for is a 404 on the function-template retrieve endpoint,
 * whose "Not found." body is not actionable; every other 4xx already carries a
 * validation detail and must not be buried under a generic hint.
 */
export function getToolRecoveryHint({ url, status }: RecoveryHintInput): string | undefined {
    // The one 4xx worth a hint: a not-found on an exact-id template lookup.
    if (status === 404 && url && HOG_FUNCTION_TEMPLATE_RETRIEVE_URL.test(url)) {
        return HOG_FUNCTION_TEMPLATE_NOT_FOUND_HINT
    }
    // Every other 4xx is recoverable agent input, already surfaced verbatim upstream.
    if (status !== undefined && status < 500) {
        return undefined
    }
    if (url && LOGS_QUERY_URL_FRAGMENTS.some((fragment) => url.includes(fragment))) {
        return LOGS_QUERY_RECOVERY_HINT
    }
    return undefined
}
