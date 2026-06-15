/**
 * Provenance of a tool result's content — does it carry data the agent and its
 * author control, or data influenced by something outside that boundary?
 *
 *   - `internal` — first-party / agent-owned output: the agent's own memory and
 *     tables, control-flow meta tools, confirmations of actions it took.
 *   - `external` — output that can carry attacker-influenceable content: web
 *     pages, arbitrary HTTP bodies, third-party MCP servers, messages read from
 *     Slack, sandboxed custom-tool code, client-supplied results, and end-user
 *     event/person data surfaced by analytics queries.
 *
 * Stamped onto each persisted `ToolResultMessage` by the runner. It is a label,
 * not a gate: it gives a later detection / policy layer a machine-readable way
 * to tell trusted output from untrusted, and makes "did external content reach
 * the model before an egress call?" answerable from the transcript.
 */
export type ToolResultProvenance = 'internal' | 'external'

/**
 * Native tool ids whose results can carry content from outside the agent's and
 * author's control. Conservative by design — when a tool's output could include
 * anything an end user or third party authored, it belongs here (false external
 * labels are cheap; a missed one hides a real injection vector). This is the
 * shared taxonomy a spec-level data-flow check can reuse.
 */
export const EXTERNAL_CONTENT_NATIVE_TOOL_IDS: ReadonlySet<string> = new Set([
    '@posthog/web-search',
    '@posthog/web-fetch',
    '@posthog/http-request',
    '@posthog/slack-read-channel',
    '@posthog/slack-read-thread',
    // Analytics results can contain end-user-authored strings (event names,
    // person properties, cohort names), so treat them as external content.
    '@posthog/query',
])

/** Provenance for a native tool's result, by id. Unknown ids default to
 *  `internal` — first-party native tools are the norm; any native tool that
 *  surfaces outside content must be added to `EXTERNAL_CONTENT_NATIVE_TOOL_IDS`. */
export function nativeToolResultProvenance(id: string): ToolResultProvenance {
    return EXTERNAL_CONTENT_NATIVE_TOOL_IDS.has(id) ? 'external' : 'internal'
}
