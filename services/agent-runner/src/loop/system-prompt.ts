/**
 * Build the system prompt from the revision bundle. Three layers:
 *
 *   1. Framework preamble — platform-owned guidance about the state
 *      machine, meta tools, and (slice 2+) tool failure / approval
 *      handling / reasoning hints. See `framework-preamble.ts` and
 *      `docs/agent-platform/plans/framework-system-prompt.md`.
 *   2. agent.md (or spec.entrypoint) — author-owned instructions. Wins
 *      over the preamble through normal natural-language precedence
 *      (the model reads it after).
 *   3. Skills index — listed as one line per skill (`- <id>: <description>`).
 *      The model calls `@posthog/load-skill` (auto-included by the
 *      runner when spec.skills is non-empty) to fetch a body on
 *      demand. Keeps per-turn token usage low for agents with many
 *      skills.
 */

import { AgentRevision, BundleStore } from '@posthog/agent-shared'

import { renderFrameworkPreamble } from './framework-preamble'

export async function buildSystemPrompt(rev: AgentRevision, bundle: BundleStore): Promise<string> {
    const parts: string[] = []

    // Framework preamble first — the author's agent.md can override its
    // defaults via normal natural-language instructions.
    parts.push(renderFrameworkPreamble(rev))

    const entry = rev.spec.entrypoint || 'agent.md'
    if (await bundle.exists(rev.id, entry)) {
        parts.push(await bundle.readText(rev.id, entry))
    } else {
        parts.push('(missing entrypoint — please add agent.md)')
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
