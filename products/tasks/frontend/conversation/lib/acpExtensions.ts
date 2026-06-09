/**
 * PostHog-specific ACP extension constants and matchers.
 *
 * Vendored from packages/agent/src/acp-extensions.ts (the reference imports
 * these from `@posthog/agent`, which does not exist in posthog/posthog). Only
 * the notification methods and `isNotification` matcher used by the
 * conversation pipeline are copied.
 */

export const POSTHOG_NOTIFICATIONS = {
    /** Agent finished processing a turn (prompt returned, waiting for next input) */
    TURN_COMPLETE: '_posthog/turn_complete',
    /** Error occurred during task execution */
    ERROR: '_posthog/error',
    /** Console/log output from the agent */
    CONSOLE: '_posthog/console',
    /** Agent status update (thinking, working, etc.) */
    STATUS: '_posthog/status',
    /** Structured backend progress notification; events in the same turn group into one card */
    PROGRESS: '_posthog/progress',
    /** Task-level notification (progress, milestones) */
    TASK_NOTIFICATION: '_posthog/task_notification',
    /** Marks a boundary for log compaction */
    COMPACT_BOUNDARY: '_posthog/compact_boundary',
    /** Token usage update for a session turn */
    USAGE_UPDATE: '_posthog/usage_update',
    /** PostHog products used during a turn (derived from MCP exec calls) */
    RESOURCES_USED: '_posthog/resources_used',
} as const

type PosthogNotification = (typeof POSTHOG_NOTIFICATIONS)[keyof typeof POSTHOG_NOTIFICATIONS]

/**
 * Does `method` match `expected`? Handles the `__posthog/` double-prefix that
 * `extNotification()` can produce.
 */
function matchesExt(method: string | undefined, expected: string): boolean {
    if (!method) {
        return false
    }
    return method === expected || method === `_${expected}`
}

export function isNotification(method: string | undefined, expected: PosthogNotification): boolean {
    return matchesExt(method, expected)
}
