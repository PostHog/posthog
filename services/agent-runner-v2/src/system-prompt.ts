/**
 * Build the system prompt from the revision bundle.
 * - agent.md (or spec.entrypoint) — the top-level instructions
 * - skills/* referenced in spec.skills — appended in order with a heading per skill
 */

import { AgentRevision, BundleStore } from '@posthog/agent-shared-v2'

export async function buildSystemPrompt(rev: AgentRevision, bundle: BundleStore): Promise<string> {
    const parts: string[] = []
    const entry = rev.spec.entrypoint || 'agent.md'
    if (await bundle.exists(rev.id, entry)) {
        parts.push(await bundle.readText(rev.id, entry))
    } else {
        parts.push('# Agent\n\n(missing entrypoint — please add agent.md)')
    }

    for (const skill of rev.spec.skills) {
        if (!(await bundle.exists(rev.id, skill.path))) {
            continue
        }
        const body = await bundle.readText(rev.id, skill.path)
        parts.push(`\n\n---\n\n## Skill: ${skill.id}\n\n${body}`)
    }
    return parts.join('\n')
}
