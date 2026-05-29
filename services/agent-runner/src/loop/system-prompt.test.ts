import { AgentSpecSchema, MemoryBundleStore } from '@posthog/agent-shared'

import { buildSystemPrompt } from './system-prompt'

function makeRev(spec: ReturnType<typeof AgentSpecSchema.parse>): never {
    return {
        id: 'rev1',
        application_id: 'app',
        parent_revision_id: null,
        created_by_id: null,
        created_at: '2026-05-27',
        state: 'live',
        bundle_uri: 's3://x/',
        bundle_sha256: null,
        spec,
    } as never
}

describe('buildSystemPrompt', () => {
    it('reads agent.md and emits a skill INDEX (not bodies)', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'You are a helpful agent.')
        await bundle.write('rev1', 'skills/research.md', 'Be thorough.')
        await bundle.write('rev1', 'skills/cite.md', 'Cite sources.')
        const spec = AgentSpecSchema.parse({
            model: 'x',
            skills: [
                { id: 'research', path: 'skills/research.md', description: 'How to research a question' },
                { id: 'cite', path: 'skills/cite.md', description: 'Citation formatting' },
            ],
        })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle)

        expect(prompt).toContain('You are a helpful agent.')
        // Index lists each skill with its id + description.
        expect(prompt).toContain('Available skills')
        expect(prompt).toContain('@posthog/load-skill')
        expect(prompt).toContain('`research`: How to research a question')
        expect(prompt).toContain('`cite`: Citation formatting')
        // Bodies must NOT be inlined — that's the whole point of B1.
        expect(prompt).not.toContain('Be thorough.')
        expect(prompt).not.toContain('Cite sources.')
    })

    it('skills without a description fall back to a placeholder in the index', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'top')
        const spec = AgentSpecSchema.parse({
            model: 'x',
            skills: [{ id: 'mystery', path: 'skills/mystery.md' }],
        })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle)
        expect(prompt).toContain('`mystery`: (no description)')
    })

    it('emits no skills section when spec.skills is empty', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'top')
        const spec = AgentSpecSchema.parse({ model: 'x' })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle)
        expect(prompt).not.toContain('Available skills')
    })

    it('falls back when entrypoint missing', async () => {
        const bundle = new MemoryBundleStore()
        const spec = AgentSpecSchema.parse({ model: 'x' })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle)
        expect(prompt).toMatch(/missing entrypoint/)
    })

    it('injects the framework preamble before agent.md', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'I am the agent author content.')
        const spec = AgentSpecSchema.parse({ model: 'x' })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle)

        // Preamble lands first so the author's instructions appear
        // *after* it — natural-language precedence lets agent.md
        // override the framework defaults.
        const preambleIdx = prompt.indexOf('Platform guidance')
        const authorIdx = prompt.indexOf('I am the agent author content.')
        expect(preambleIdx).toBeGreaterThanOrEqual(0)
        expect(authorIdx).toBeGreaterThan(preambleIdx)
    })

    it('framework preamble covers meta-tool decision rules + state contract', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const spec = AgentSpecSchema.parse({ model: 'x' })
        const prompt = await buildSystemPrompt(makeRev(spec), bundle)

        // §3.1 — meta-tool decision rules. Each of the three meta tools
        // is named and pi-ai will see explicit framing about when to
        // use which.
        expect(prompt).toContain('@posthog/meta-end-turn')
        expect(prompt).toContain('@posthog/meta-end-session')
        expect(prompt).toContain('@posthog/meta-ask-for-input')
        // Default-first framing — the model should default to end-turn,
        // not end-session. The prose explicitly calls out end-turn as
        // the default; assert both terms colocate.
        const endTurnSection = prompt.split('@posthog/meta-end-turn')[1]?.split('@posthog/meta-ask-for-input')[0] ?? ''
        expect(endTurnSection).toMatch(/default/i)

        // §3.2 — conversation-state contract.
        expect(prompt).toContain('Conversation state')
        expect(prompt).toContain('completed')
        expect(prompt).toContain('closed')
    })
})
