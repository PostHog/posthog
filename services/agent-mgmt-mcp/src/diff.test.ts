import { AgentSpecSchema, MemoryBundleStore } from '@posthog/agent-shared-v2'

import { diffFiles, diffSpec } from './diff'

describe('diffSpec', () => {
    it('detects model change', () => {
        const a = AgentSpecSchema.parse({ model: 'claude-sonnet-4-6' })
        const b = AgentSpecSchema.parse({ model: 'claude-opus-4-7' })
        const d = diffSpec(a, b)
        expect(d.model).toEqual({ before: 'claude-sonnet-4-6', after: 'claude-opus-4-7' })
    })

    it('detects tools added / removed', () => {
        const a = AgentSpecSchema.parse({
            model: 'x',
            tools: [{ kind: 'native', id: 'posthog.query.v1' }],
        })
        const b = AgentSpecSchema.parse({
            model: 'x',
            tools: [{ kind: 'native', id: 'slack.post_message.v1' }],
        })
        const d = diffSpec(a, b)
        expect(d.tools.added).toEqual(['slack.post_message.v1'])
        expect(d.tools.removed).toEqual(['posthog.query.v1'])
    })

    it('detects limit changes', () => {
        const a = AgentSpecSchema.parse({ model: 'x' })
        const b = AgentSpecSchema.parse({
            model: 'x',
            limits: { max_turns: 10, max_tool_calls: 50, max_wall_seconds: 60 },
        })
        const d = diffSpec(a, b)
        expect(d.limits.max_turns).toEqual({ before: 50, after: 10 })
    })

    it('no diff when specs are equal', () => {
        const a = AgentSpecSchema.parse({ model: 'x' })
        const d = diffSpec(a, a)
        expect(d.model).toBeNull()
        expect(d.tools.added).toEqual([])
        expect(d.tools.removed).toEqual([])
    })
})

describe('diffFiles', () => {
    it('classifies added/removed/modified/unchanged', async () => {
        const b = new MemoryBundleStore()
        await b.write('a', 'agent.md', 'old prompt')
        await b.write('a', 'skills/x.md', 'shared')
        await b.write('b', 'agent.md', 'new prompt')
        await b.write('b', 'skills/x.md', 'shared')
        await b.write('b', 'skills/y.md', 'added')
        const d = await diffFiles(b, 'a', 'b')
        const by = (p: string): (typeof d)[number] => d.find((x) => x.path === p)!
        expect(by('agent.md').kind).toBe('modified')
        expect(by('skills/x.md').kind).toBe('unchanged')
        expect(by('skills/y.md').kind).toBe('added')
    })
})
