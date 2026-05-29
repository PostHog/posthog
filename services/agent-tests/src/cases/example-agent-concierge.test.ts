/**
 * Example bundle wiring check — `services/agent-tests/src/examples/agent-concierge/`.
 *
 * The concierge bundle is a forward-looking reference: it uses
 * `kind: "client"` tool refs and `spec.mcps[]` that today's runner
 * doesn't fully wire (see `docs/agent-platform/plans/agent-concierge.md`
 * §8 for the gap list). So this case can't deploy + drive the agent
 * end-to-end the way `example-sre-bot.test.ts` does.
 *
 * Instead it pins the wiring net: every skill path declared in spec
 * exists as a file, every MCP tool the concierge declares matches
 * the authoring MCP catalog, and `agent.md` is non-trivial. If any
 * of these drifts, the bundle is broken regardless of platform
 * readiness — this case catches it before review.
 */

import { readdir, readFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BUNDLE_ROOT = resolve(__dirname, '../examples/agent-concierge')
const AGENT_STACK_YAML = resolve(__dirname, '../../../mcp/definitions/agent_stack.yaml')

interface ConciergeSpec {
    model: string
    triggers: Array<{ type: string }>
    tools: Array<{ kind: string; id?: string; from_native?: string }>
    mcps: Array<{ id: string; endpoint: string; tools: string[]; secrets: string[] }>
    skills: Array<{ id: string; path: string; description: string }>
    integrations: string[]
    secrets: string[]
    limits: { max_turns: number; max_tool_calls: number; max_wall_seconds: number }
    auth: { mode: string }
    reasoning?: string
}

async function loadBundle(): Promise<{ spec: ConciergeSpec; files: Record<string, string> }> {
    const spec = JSON.parse(await readFile(join(BUNDLE_ROOT, 'spec.json'), 'utf-8')) as ConciergeSpec
    const files: Record<string, string> = {}
    files['agent.md'] = await readFile(join(BUNDLE_ROOT, 'agent.md'), 'utf-8')
    files['README.md'] = await readFile(join(BUNDLE_ROOT, 'README.md'), 'utf-8')
    const skillFiles = await readdir(join(BUNDLE_ROOT, 'skills'))
    for (const sf of skillFiles) {
        files[`skills/${sf}`] = await readFile(join(BUNDLE_ROOT, 'skills', sf), 'utf-8')
    }
    return { spec, files }
}

async function loadAgentStackToolIds(): Promise<Set<string>> {
    // The yaml has shape `tools:\n    foo-bar:\n        operation: ...`.
    // Pulling the tool keys with a regex is cheaper than adding a yaml dep
    // for one assertion — the keys are stable, indented exactly 4 spaces.
    const raw = await readFile(AGENT_STACK_YAML, 'utf-8')
    const matches = raw.matchAll(/^ {4}([a-z][a-z0-9-]+):$/gm)
    return new Set(Array.from(matches, (m) => m[1]))
}

describe('example: agent-concierge bundle', () => {
    it('every skill path in spec.skills[] exists as a bundle file', async () => {
        const { spec, files } = await loadBundle()
        for (const skill of spec.skills) {
            expect(files[skill.path]).not.toBeUndefined()
            // Each skill description is the only signal the model gets for
            // when to load it — guard against empty / placeholder descriptions.
            expect(skill.description).toBeTruthy()
            expect(skill.description.length).toBeGreaterThan(30)
        }
    })

    it('agent.md is present and non-trivial', async () => {
        const { files } = await loadBundle()
        expect(files['agent.md']).not.toBeUndefined()
        // The concierge agent.md is intentionally short (defers to skills) but
        // not THIS short. <500 chars means something got truncated.
        expect(files['agent.md'].length).toBeGreaterThan(500)
    })

    it('every MCP tool the concierge declares matches the authoring MCP catalog', async () => {
        const { spec } = await loadBundle()
        const catalog = await loadAgentStackToolIds()
        const posthog = spec.mcps.find((m) => m.id === 'posthog')
        expect(posthog).toBeTruthy()
        for (const toolId of posthog!.tools) {
            expect(catalog.has(toolId)).toBe(true)
        }
    })

    it('declares both chat and mcp triggers (the two production surfaces)', async () => {
        const { spec } = await loadBundle()
        const triggerTypes = spec.triggers.map((t) => t.type)
        expect(triggerTypes).toContain('chat')
        expect(triggerTypes).toContain('mcp')
    })

    it('declares client tools for the console UI surface', async () => {
        const { spec } = await loadBundle()
        // The concierge MUST reference the well-known UI client tools so the
        // console handshake reconciles them — see plan §8.1.
        const clientTools = spec.tools.filter((t) => t.kind === 'client').map((t) => t.from_native)
        expect(clientTools).toContain('@posthog/ui/focus')
        expect(clientTools).toContain('@posthog/ui/toast')
    })

    it('uses posthog_internal auth (no public exposure)', async () => {
        const { spec } = await loadBundle()
        expect(spec.auth.mode).toBe('posthog_internal')
    })
})
