import { AgentSpec, AgentSpecSchema } from './spec'

describe('AgentSpecSchema', () => {
    it('parses a minimal spec with defaults', () => {
        const parsed = AgentSpecSchema.parse({ model: 'claude-opus-4-7' })
        expect(parsed.model).toBe('claude-opus-4-7')
        expect(parsed.triggers).toEqual([])
        expect(parsed.tools).toEqual([])
        expect(parsed.entrypoint).toBe('agent.md')
        expect(parsed.limits.max_turns).toBe(50)
    })

    it('parses a fully-populated spec', () => {
        const spec: AgentSpec = AgentSpecSchema.parse({
            model: 'claude-opus-4-7',
            triggers: [
                { type: 'slack', config: { channel_id: 'C01', mention_only: true } },
                { type: 'webhook', config: { path: '/hook' } },
            ],
            tools: [
                { kind: 'native', id: 'posthog.query.v1' },
                { kind: 'custom', id: 'fetch-acme', path: 'tools/fetch-acme/' },
            ],
            mcps: [{ kind: 'agent', slug: 'weekly-digest' }],
            skills: [{ id: 'deep-research', path: 'skills/deep-research.md' }],
            integrations: ['slack:T01'],
            secrets: ['ACME_KEY'],
            limits: { max_turns: 10, max_tool_calls: 50, max_wall_seconds: 300 },
            entrypoint: 'agent.md',
        })
        expect(spec.triggers).toHaveLength(2)
        expect(spec.tools).toHaveLength(2)
        expect(spec.mcps[0]).toEqual({ kind: 'agent', slug: 'weekly-digest' })
    })

    it('rejects unknown trigger type', () => {
        expect(() =>
            AgentSpecSchema.parse({ model: 'x', triggers: [{ type: 'carrier-pigeon', config: {} }] })
        ).toThrow()
    })

    it('rejects unknown tool kind', () => {
        expect(() => AgentSpecSchema.parse({ model: 'x', tools: [{ kind: 'rogue', id: 'x' }] })).toThrow()
    })
})
