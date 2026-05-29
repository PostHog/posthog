/**
 * Build the pi-ai `Tool[]` list for a session from the revision spec.
 *
 * Two sources of tools:
 *   1. Always-on natives: meta control-flow (ask_for_input, end_session) and,
 *      conditionally, `@posthog/load-skill` when the agent has skills. These
 *      don't need to be listed in `spec.tools` — the runner injects them so
 *      every agent can suspend, end, or load skills regardless of how the
 *      spec was authored.
 *   2. Whatever `spec.tools` declares — native or custom. Native tools are
 *      looked up by id in the central native registry; custom tools have
 *      their description + args loaded from `<path>/schema.json` in the
 *      bundle (with a permissive fallback if the file is missing / malformed).
 *
 * Provider-safe name translation happens in run-turn.ts — `buildToolList`
 * returns names as their internal ids; the caller sanitizes at the pi-ai
 * boundary and builds a reverse map for tool-call dispatch.
 */

import type { Tool } from '@earendil-works/pi-ai'

import { AgentRevision, BundleStore } from '@posthog/agent-shared'
import { listNativeTools } from '@posthog/agent-tools'

/**
 * Meta control-flow tools — always exposed to the model, even if the agent
 * spec doesn't list them. Without these the model can't suspend (ask the
 * user) or cleanly end a session. Kept in sync with `AUTO_INCLUDED_NATIVES`
 * in tool-dispatch.ts (which knows how to dispatch these without a spec.tools
 * lookup).
 */
export const ALWAYS_ON_NATIVE_TOOL_IDS = [
    '@posthog/meta-end-turn',
    '@posthog/meta-ask-for-input',
    '@posthog/meta-end-session',
]

export async function buildToolList(rev: AgentRevision, bundle: BundleStore): Promise<Tool[]> {
    const decls: Tool[] = []
    const seen = new Set<string>()
    // `@posthog/load-skill` is auto-included only when the agent has skills —
    // exposing it to a skill-less agent just adds a tool that errors on use.
    const alwaysOn = [...ALWAYS_ON_NATIVE_TOOL_IDS]
    if (rev.spec.skills.length > 0) {
        alwaysOn.push('@posthog/load-skill')
    }
    const allTools = [...alwaysOn.map((id) => ({ kind: 'native' as const, id })), ...rev.spec.tools]
    for (const t of allTools) {
        if (seen.has(t.id)) {
            continue
        }
        seen.add(t.id)
        if (t.kind === 'native') {
            const native = listNativeTools().find((n) => n.id === t.id)
            if (!native) {
                continue
            }
            decls.push({
                name: native.id,
                description: native.schema.description,
                parameters: native.schema.args,
            })
        } else {
            const schemaPath = `${t.path.replace(/\/$/, '')}/schema.json`
            try {
                const raw = await bundle.readText(rev.id, schemaPath)
                const schema = JSON.parse(raw) as { description?: string; args?: unknown }
                decls.push({
                    name: t.id,
                    description: schema.description ?? `custom tool ${t.id}`,
                    parameters: (schema.args as Tool['parameters']) ?? ({ type: 'object' } as Tool['parameters']),
                })
            } catch {
                decls.push({
                    name: t.id,
                    description: `custom tool ${t.id}`,
                    parameters: { type: 'object' } as Tool['parameters'],
                })
            }
        }
    }
    return decls
}
