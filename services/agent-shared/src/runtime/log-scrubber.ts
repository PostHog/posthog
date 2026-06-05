/**
 * Redacts well-known bearer-token prefixes from log strings.
 *
 * Used by the runner before pushing crash messages into the session
 * LogSink — see `session-failure-observability.md`. Defense in depth: the
 * MCP SDK and our own native tools shouldn't echo secrets into errors,
 * but if they do, we don't want raw tokens landing in the
 * console-visible Logs tab.
 *
 * Strategy: per-prefix regex matching `<prefix><non-whitespace>` and
 * replacing the matched span with `<prefix>****`. Keeps the *kind* of
 * token visible (so an operator can diagnose "GitHub PAT leaked into an
 * error string") without leaking the value.
 *
 * Pure function — no I/O, no module-level state — so it's safe to call
 * from any layer (runner catch block, ingress error responses, ad-hoc
 * debugging). Cheap enough that callers shouldn't need to think about
 * when to skip it.
 */

/**
 * Bearer-token prefixes we recognize and redact. Order matters: the more
 * specific prefix must come first when one is a prefix of another (e.g.
 * `github_pat_` before any hypothetical `github_*`) so the matcher
 * doesn't split a token at the wrong boundary.
 */
const TOKEN_PREFIXES: readonly string[] = [
    // Slack — bot, user, app-level, and analytics tokens
    'xoxb-',
    'xoxp-',
    'xapp-',
    'xoxa-',
    // GitHub — classic PAT, fine-grained PAT, OAuth user-to-server,
    // user, app installation
    'github_pat_',
    'ghp_',
    'gho_',
    'ghu_',
    'ghs_',
    // OpenAI / Anthropic-style API keys
    'sk-',
    // Notion integration tokens
    'ntn_',
    // Linear personal API keys
    'lin_api_',
]

/**
 * Escape regex metacharacters in a literal prefix string. Keeps the
 * scrubber robust against future prefixes that include dots or dashes
 * the regex engine would otherwise interpret.
 */
function escapeRegex(literal: string): string {
    return literal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * Single compiled regex matching any known prefix followed by one or
 * more non-whitespace characters. Compiled once at module load — the
 * scrubber is hot-path-adjacent (every session crash) so this matters
 * more than the readability gain of compiling per call.
 */
const SCRUB_RE = new RegExp(TOKEN_PREFIXES.map((p) => escapeRegex(p) + '\\S+').join('|'), 'gi')

/**
 * Replace every recognized token in `input` with `<prefix>****`.
 *
 * Empty input → empty output. Input with no known token shapes →
 * unchanged. Behavior is idempotent: scrubbing already-scrubbed text is
 * a no-op because `****` contains no token-prefix characters.
 */
export function scrubTokens(input: string): string {
    if (input.length === 0) {
        return input
    }
    return input.replace(SCRUB_RE, (match) => {
        // Restore the prefix by re-matching against the known set. The
        // outer regex is case-insensitive (Slack tokens are sometimes
        // upper-cased in copy-paste), so we use the same `toLowerCase`
        // comparison the original prefix list assumes.
        const lower = match.toLowerCase()
        for (const prefix of TOKEN_PREFIXES) {
            if (lower.startsWith(prefix)) {
                // Preserve the original-case prefix as the caller wrote
                // it — case can be diagnostically useful ("user typed
                // XOXB-... not xoxb-...").
                return match.slice(0, prefix.length) + '****'
            }
        }
        // Unreachable if SCRUB_RE is in sync with TOKEN_PREFIXES; defensive
        // fallback if a future edit adds a prefix to the regex but not the
        // list (or vice versa).
        return '****'
    })
}
