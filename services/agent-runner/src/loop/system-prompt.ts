/**
 * Build the system prompt from the revision bundle.
 *
 * - agent.md (or spec.entrypoint) — top-level instructions.
 * - skills/* — listed as an INDEX, not inlined. Each entry is one line:
 *   `- <id>: <description>`. The model calls `@posthog/load-skill` (auto-
 *   included by the runner when spec.skills is non-empty) to fetch a body
 *   on demand. Keeps per-turn token usage low for agents with many skills.
 */

import { AgentRevision, BundleStore } from '@posthog/agent-shared'

export async function buildSystemPrompt(rev: AgentRevision, bundle: BundleStore): Promise<string> {
    const parts: string[] = []
    const entry = rev.spec.entrypoint || 'agent.md'
    if (await bundle.exists(rev.id, entry)) {
        parts.push(await bundle.readText(rev.id, entry))
    } else {
        parts.push('# Agent\n\n(missing entrypoint — please add agent.md)')
    }

    if (rev.spec.skills.length > 0) {
        const lines = ['\n\n---\n\n## Available skills', '']
        lines.push('Call `@posthog/load-skill` with one of these ids to fetch the full body when you need it:')
        lines.push('')
        for (const skill of rev.spec.skills) {
            const desc = skill.description?.trim() || '(no description)'
            lines.push(`- \`${skill.id}\`: ${desc}`)
        }
        parts.push(lines.join('\n'))
    }
    return parts.join('\n')
}
