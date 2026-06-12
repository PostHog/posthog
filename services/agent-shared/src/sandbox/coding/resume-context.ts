/**
 * Supervisor-side conversation replay for coding re-claims.
 *
 * A completed coding session tears down its sandbox, so a follow-up /send
 * boots a fresh harness with no memory of prior turns. The harness's own
 * resume path (`POSTHOG_RESUME_RUN_ID`) ultimately does the same thing this
 * module does — formats the prior conversation as markdown and injects it
 * into the first prompt — but it depends on fetching the previous run's log
 * from the PostHog API, which the supervisor doesn't serve. Since the
 * supervisor already holds the authoritative `session.conversation`, it
 * formats the history itself and wraps the first `user_message` of the
 * re-claimed invocation.
 *
 * The wording deliberately mirrors the harness's resume prompt
 * (packages/agent/src/resume.ts + agent-server.ts in posthog/code): its
 * `isResumeContextTurn` detection keys off these exact phrases, so these
 * turns are recognized and filtered if native harness resume lands later.
 * Workspace state is NOT restored — that needs sandbox snapshots (separate
 * lifecycle work); the preamble says so to keep the model honest.
 */

import type { ConversationMessage } from '../../spec/spec'

const TOOL_RESULT_MAX_CHARS = 2000
/** ~25k tokens — same order as the harness's 50k-token resume budget, conservatively. */
const HISTORY_MAX_CHARS = 100_000

function textOf(content: string | { type: string; text?: string }[]): string {
    if (typeof content === 'string') {
        return content
    }
    return content
        .filter((b) => b.type === 'text' && typeof b.text === 'string')
        .map((b) => b.text)
        .join('\n')
}

function truncate(text: string): string {
    return text.length > TOOL_RESULT_MAX_CHARS ? `${text.slice(0, TOOL_RESULT_MAX_CHARS)}...(truncated)` : text
}

/**
 * Format a persisted conversation as the markdown history block the harness's
 * own resume produces: `**User**:` / `**Assistant**:` turns, with tool calls
 * folded into an `**Assistant (tools)**:` summary (result truncated). Keeps
 * the most recent turns within a char budget, noting how many were dropped.
 * Returns null when there's nothing to replay.
 */
export function formatConversationForResume(conversation: ConversationMessage[]): string | null {
    // Pair tool results with their originating assistant toolCall blocks.
    const resultsById = new Map<string, { output: string; isError: boolean }>()
    for (const msg of conversation) {
        if (msg.role === 'toolResult') {
            resultsById.set(msg.toolCallId, { output: textOf(msg.content), isError: msg.isError })
        }
    }

    const parts: string[] = []
    for (const msg of conversation) {
        if (msg.role === 'user') {
            const text = textOf(msg.content).trim()
            if (text) {
                parts.push(`**User**: ${text}`)
            }
            continue
        }
        if (msg.role !== 'assistant') {
            continue // toolResults are folded into the assistant turn above
        }
        const text = msg.content
            .filter((b) => b.type === 'text')
            .map((b) => b.text)
            .join('\n')
            .trim()
        if (text) {
            parts.push(`**Assistant**: ${text}`)
        }
        const toolLines = msg.content
            .filter((b) => b.type === 'toolCall')
            .map((tc) => {
                const result = resultsById.get(tc.id)
                const suffix = result ? ` → ${truncate(result.output)}` : ''
                return `  - ${tc.name}${suffix}`
            })
        if (toolLines.length > 0) {
            parts.push(`**Assistant (tools)**:\n${toolLines.join('\n')}`)
        }
    }
    if (parts.length === 0) {
        return null
    }

    // Keep the most recent parts within budget; note what was dropped.
    const kept: string[] = []
    let used = 0
    for (let i = parts.length - 1; i >= 0; i--) {
        used += parts[i].length + 2
        if (used > HISTORY_MAX_CHARS && kept.length > 0) {
            kept.unshift(`*(${i + 1} earlier turns omitted)*`)
            break
        }
        kept.unshift(parts[i])
    }
    return kept.join('\n\n')
}

/** Wrap the first user message of a re-claim in the harness-style resume preamble. */
export function buildResumePrompt(history: string, newMessage: string): string {
    return (
        `You are resuming a previous conversation. The workspace from the previous session was not restored, ` +
        `so you are starting with a fresh environment. Your conversation history is fully preserved below.\n\n` +
        `Here is the conversation history from the previous session:\n\n` +
        `${history}\n\n` +
        `The user has sent a new message:\n\n` +
        `${newMessage}\n\n` +
        `Respond to the user's new message above. You have full context from the previous session.`
    )
}
