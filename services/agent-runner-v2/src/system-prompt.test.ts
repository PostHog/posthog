import { AgentSpecSchema, MemoryBundleStore } from '@posthog/agent-shared-v2'

import { buildSystemPrompt } from './system-prompt'

describe('buildSystemPrompt', () => {
    it('reads agent.md and appends referenced skills', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'You are a helpful agent.')
        await bundle.write('rev1', 'skills/research.md', 'Be thorough.')
        await bundle.write('rev1', 'skills/cite.md', 'Cite sources.')
        const spec = AgentSpecSchema.parse({
            model: 'x',
            skills: [
                { id: 'research', path: 'skills/research.md' },
                { id: 'cite', path: 'skills/cite.md' },
            ],
        })
        const prompt = await buildSystemPrompt(
            {
                id: 'rev1',
                application_id: 'app',
                parent_revision_id: null,
                created_by: 'u',
                created_at: '2026-05-27',
                state: 'live',
                bundle_uri: 's3://x/',
                bundle_sha256: null,
                spec,
            },
            bundle
        )
        expect(prompt).toContain('You are a helpful agent.')
        expect(prompt).toContain('## Skill: research')
        expect(prompt).toContain('Be thorough.')
        expect(prompt).toContain('## Skill: cite')
    })

    it('skips missing skill files silently', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'top')
        const spec = AgentSpecSchema.parse({
            model: 'x',
            skills: [{ id: 'ghost', path: 'skills/ghost.md' }],
        })
        const prompt = await buildSystemPrompt(
            {
                id: 'rev1',
                application_id: 'a',
                parent_revision_id: null,
                created_by: 'u',
                created_at: 'now',
                state: 'live',
                bundle_uri: 's3://',
                bundle_sha256: null,
                spec,
            },
            bundle
        )
        expect(prompt).toContain('top')
        expect(prompt).not.toContain('## Skill: ghost')
    })

    it('falls back when entrypoint missing', async () => {
        const bundle = new MemoryBundleStore()
        const spec = AgentSpecSchema.parse({ model: 'x' })
        const prompt = await buildSystemPrompt(
            {
                id: 'rev1',
                application_id: 'a',
                parent_revision_id: null,
                created_by: 'u',
                created_at: 'now',
                state: 'live',
                bundle_uri: 's3://',
                bundle_sha256: null,
                spec,
            },
            bundle
        )
        expect(prompt).toMatch(/missing entrypoint/)
    })
})
