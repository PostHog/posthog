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

/**
 * A 404 from `project-get`/`project-settings-update` means the id doesn't exist
 * in this org (or isn't accessible). Because there's no name-based project
 * lookup, agents respond by guessing another id — each miss is another hard 404,
 * which is the bulk of `project-get`'s error rate. Point them at `projects-get`
 * (which returns every accessible project's `id` and `name`) so they resolve the
 * project by name in one call instead of brute-forcing numbers.
 */
const PROJECT_NOT_FOUND_RECOVERY_HINT = [
    "No project with that id exists in this organization, or you don't have access to it. Don't guess project ids by trying other numbers.",
    '',
    'To find the right project:',
    '1. Call `projects-get` to list every project you can access — each result carries its `id` and `name`.',
    '2. Match the one you want by `name`, then retry with that `id` (or call `switch-project { projectId: <id> }` to make it active).',
].join('\n')

/**
 * Matches the project retrieve/update endpoint
 * (`/api/organizations/<org>/projects/<id>/`). Deliberately anchored to the
 * `organizations/.../projects/<id>` shape so it doesn't fire on the far more
 * common `/api/projects/<id>/<sub-resource>/` URLs, whose 404s mean the
 * sub-resource is missing, not the project.
 */
const PROJECT_RETRIEVE_URL_PATTERN = /\/organizations\/[^/]+\/projects\/[^/]+\/?$/

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
 * Most 4xx responses already carry an actionable validation detail and must not
 * be buried under a generic hint, so hints default to server-side failures (5xx)
 * and non-HTTP errors with no status. The one exception is a 404 on the project
 * retrieve endpoint: a bare "not found" gives the agent nothing to route on, so
 * it keeps guessing ids — that case gets a targeted name-lookup hint.
 */
export function getToolRecoveryHint({ url, status }: RecoveryHintInput): string | undefined {
    // Targeted 404: a missing project id, where the recovery is a name lookup
    // rather than the "narrow and retry" shape the generic 4xx guard assumes.
    if (status === 404 && url && PROJECT_RETRIEVE_URL_PATTERN.test(url)) {
        return PROJECT_NOT_FOUND_RECOVERY_HINT
    }
    // Other 4xx is recoverable agent input, already surfaced verbatim upstream.
    if (status !== undefined && status < 500) {
        return undefined
    }
    if (url && LOGS_QUERY_URL_FRAGMENTS.some((fragment) => url.includes(fragment))) {
        return LOGS_QUERY_RECOVERY_HINT
    }
    return undefined
}
