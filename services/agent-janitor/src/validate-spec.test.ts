import { z } from 'zod'

import { AgentRevision, AgentSpecSchema, MemoryBundleStore } from '@posthog/agent-shared'

import { validateRevisionBundle } from './validate-spec'

// Default fixture has a `chat` trigger so every test isn't forced to declare
// one. The `no_triggers` rule is exercised explicitly below by passing
// `triggers: []`.
function mkRev(spec: Partial<z.input<typeof AgentSpecSchema>> = {}): AgentRevision {
    return {
        id: 'rev1',
        application_id: 'app1',
        parent_revision_id: null,
        created_by_id: null,
        created_at: '2026-05-27',
        state: 'draft',
        bundle_uri: 'mem://',
        bundle_sha256: null,
        spec: AgentSpecSchema.parse({
            model: 'anthropic/claude-haiku-4-5',
            triggers: [{ type: 'chat', config: { require_auth: false } }],
            ...spec,
        }),
    }
}

describe('validateRevisionBundle', () => {
    it('passes when the bundle has the entrypoint and no tools/skills are declared', async () => {
        const bundles = new MemoryBundleStore()
        await bundles.write('rev1', 'agent.md', 'hi')
        const report = await validateRevisionBundle(mkRev(), bundles)
        expect(report.ok).toBe(true)
        expect(report.errors).toEqual([])
        expect(report.resolved_natives).toEqual([])
    })

    it('reports missing_entrypoint when agent.md is absent', async () => {
        const bundles = new MemoryBundleStore()
        const report = await validateRevisionBundle(mkRev(), bundles)
        expect(report.ok).toBe(false)
        expect(report.errors).toEqual([
            { code: 'missing_entrypoint', message: expect.stringContaining('agent.md'), pointer: 'spec.entrypoint' },
        ])
    })

    it('honors a custom spec.entrypoint', async () => {
        const bundles = new MemoryBundleStore()
        await bundles.write('rev1', 'prompts/main.md', 'hi')
        const ok = await validateRevisionBundle(mkRev({ entrypoint: 'prompts/main.md' }), bundles)
        expect(ok.ok).toBe(true)
        const miss = await validateRevisionBundle(mkRev({ entrypoint: 'prompts/other.md' }), bundles)
        expect(miss.errors[0].code).toBe('missing_entrypoint')
    })

    it('catches unknown native tool ids and resolves valid ones', async () => {
        const bundles = new MemoryBundleStore()
        await bundles.write('rev1', 'agent.md', 'hi')
        const report = await validateRevisionBundle(
            mkRev({
                tools: [
                    { kind: 'native', id: '@posthog/query' },
                    { kind: 'native', id: '@posthog/does-not-exist' },
                ],
            }),
            bundles
        )
        expect(report.resolved_natives).toEqual(['@posthog/query'])
        expect(report.errors).toEqual([
            {
                code: 'unknown_native_tool',
                message: expect.stringContaining('@posthog/does-not-exist'),
                pointer: 'spec.tools[1].id',
            },
        ])
    })

    it('catches missing compiled.js / schema.json on a custom tool', async () => {
        const bundles = new MemoryBundleStore()
        await bundles.write('rev1', 'agent.md', 'hi')
        await bundles.write('rev1', 'tools/wc/schema.json', '{}')
        // compiled.js intentionally missing.
        const report = await validateRevisionBundle(
            mkRev({ tools: [{ kind: 'custom', id: 'wc', path: 'tools/wc/' }] }),
            bundles
        )
        const codes = report.errors.map((e) => e.code).sort()
        expect(codes).toEqual(['missing_custom_tool_compiled'])
    })

    it('catches a custom tool that has neither compiled.js nor schema.json', async () => {
        const bundles = new MemoryBundleStore()
        await bundles.write('rev1', 'agent.md', 'hi')
        const report = await validateRevisionBundle(
            mkRev({ tools: [{ kind: 'custom', id: 'wc', path: 'tools/wc/' }] }),
            bundles
        )
        const codes = report.errors.map((e) => e.code).sort()
        expect(codes).toEqual(['missing_custom_tool_compiled', 'missing_custom_tool_schema'])
    })

    it('catches missing skill files', async () => {
        const bundles = new MemoryBundleStore()
        await bundles.write('rev1', 'agent.md', 'hi')
        await bundles.write('rev1', 'skills/present.md', 'be thorough')
        const report = await validateRevisionBundle(
            mkRev({
                skills: [
                    { id: 'present', path: 'skills/present.md' },
                    { id: 'ghost', path: 'skills/missing.md' },
                ],
            }),
            bundles
        )
        expect(report.errors).toEqual([
            {
                code: 'missing_skill',
                message: expect.stringContaining('skills/missing.md'),
                pointer: 'spec.skills[1].path',
            },
        ])
    })

    it('reports no_triggers when spec.triggers is empty', async () => {
        const bundles = new MemoryBundleStore()
        await bundles.write('rev1', 'agent.md', 'hi')
        const report = await validateRevisionBundle(mkRev({ triggers: [] }), bundles)
        expect(report.ok).toBe(false)
        expect(report.errors).toEqual([
            {
                code: 'no_triggers',
                message: expect.stringContaining('no entry points'),
                pointer: 'spec.triggers',
            },
        ])
    })

    it('returns revision state alongside the report', async () => {
        const bundles = new MemoryBundleStore()
        await bundles.write('rev1', 'agent.md', 'hi')
        const rev = mkRev()
        rev.state = 'ready'
        const report = await validateRevisionBundle(rev, bundles)
        expect(report.revision_state).toBe('ready')
        expect(report.revision_id).toBe('rev1')
    })
})
