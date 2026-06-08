import type { S3Client } from '@aws-sdk/client-s3'
import { z } from 'zod'

import {
    AgentRevision,
    AgentSpecSchema,
    buildTestBundleStore,
    newTestPrefix,
    S3BundleStore,
    wipeTestPrefix,
} from '@posthog/agent-shared'

import { validateRevisionBundle } from './validate-spec'

let bundlePrefix: string
let bundleClient: S3Client
let bundleStore: S3BundleStore

beforeEach(() => {
    bundlePrefix = newTestPrefix('agent_bundles_validate_spec_test')
    const built = buildTestBundleStore(bundlePrefix)
    bundleClient = built.client
    bundleStore = built.store
})

afterEach(async () => {
    await wipeTestPrefix(bundleClient, bundlePrefix).catch(() => undefined)
    bundleClient.destroy()
})

function makeBundles(): S3BundleStore {
    return bundleStore
}

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
        const bundles = makeBundles()
        await bundles.write('rev1', 'agent.md', 'hi')
        const report = await validateRevisionBundle(mkRev(), bundles)
        expect(report.ok).toBe(true)
        expect(report.errors).toEqual([])
        expect(report.resolved_natives).toEqual([])
    })

    it('reports missing_entrypoint when agent.md is absent', async () => {
        const bundles = makeBundles()
        const report = await validateRevisionBundle(mkRev(), bundles)
        expect(report.ok).toBe(false)
        expect(report.errors).toEqual([
            { code: 'missing_entrypoint', message: expect.stringContaining('agent.md'), pointer: 'spec.entrypoint' },
        ])
    })

    it('honors a custom spec.entrypoint', async () => {
        const bundles = makeBundles()
        await bundles.write('rev1', 'prompts/main.md', 'hi')
        const ok = await validateRevisionBundle(mkRev({ entrypoint: 'prompts/main.md' }), bundles)
        expect(ok.ok).toBe(true)
        const miss = await validateRevisionBundle(mkRev({ entrypoint: 'prompts/other.md' }), bundles)
        expect(miss.errors[0].code).toBe('missing_entrypoint')
    })

    it('catches unknown native tool ids and resolves valid ones', async () => {
        const bundles = makeBundles()
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

    it("catches missing source.ts on a custom tool (compiled.js is no longer the author's job)", async () => {
        const bundles = makeBundles()
        await bundles.write('rev1', 'agent.md', 'hi')
        await bundles.write('rev1', 'tools/wc/schema.json', '{}')
        // source.ts intentionally missing. Authors write source.ts; the
        // janitor produces compiled.js at freeze.
        const report = await validateRevisionBundle(
            mkRev({ tools: [{ kind: 'custom', id: 'wc', path: 'tools/wc/' }] }),
            bundles
        )
        const codes = report.errors.map((e) => e.code).sort()
        expect(codes).toEqual(['missing_custom_tool_source'])
    })

    it('catches a custom tool that has neither source.ts nor schema.json', async () => {
        const bundles = makeBundles()
        await bundles.write('rev1', 'agent.md', 'hi')
        const report = await validateRevisionBundle(
            mkRev({ tools: [{ kind: 'custom', id: 'wc', path: 'tools/wc/' }] }),
            bundles
        )
        const codes = report.errors.map((e) => e.code).sort()
        expect(codes).toEqual(['missing_custom_tool_schema', 'missing_custom_tool_source'])
    })

    it('passes a custom tool that only has source.ts + schema.json (no compiled.js needed)', async () => {
        const bundles = makeBundles()
        await bundles.write('rev1', 'agent.md', 'hi')
        await bundles.write('rev1', 'tools/wc/schema.json', '{}')
        await bundles.write(
            'rev1',
            'tools/wc/source.ts',
            'export default async function run(args: Record<string, unknown>) { return { ok: true } }'
        )
        const report = await validateRevisionBundle(
            mkRev({ tools: [{ kind: 'custom', id: 'wc', path: 'tools/wc/' }] }),
            bundles
        )
        expect(report.errors).toEqual([])
        expect(report.warnings).toEqual([])
    })

    it('catches a syntax error in source.ts via esbuild parse', async () => {
        // The whole point of validating source.ts at validate time — give
        // the concierge an actionable error before freeze instead of a
        // session-start failure.
        const bundles = makeBundles()
        await bundles.write('rev1', 'agent.md', 'hi')
        await bundles.write('rev1', 'tools/broken/schema.json', '{}')
        await bundles.write(
            'rev1',
            'tools/broken/source.ts',
            'export default async function run(args { return { ok: true } }' // missing colon, missing colon
        )
        const report = await validateRevisionBundle(
            mkRev({ tools: [{ kind: 'custom', id: 'broken', path: 'tools/broken/' }] }),
            bundles
        )
        const codes = report.errors.map((e) => e.code)
        expect(codes).toContain('invalid_custom_tool_source')
        const invalid = report.errors.find((e) => e.code === 'invalid_custom_tool_source')!
        expect(invalid.message).toContain('source.ts failed to parse')
        expect(invalid.pointer).toBe('spec.tools[0].path')
    })

    it('catches missing skill files', async () => {
        const bundles = makeBundles()
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

    describe('orphan warnings (non-blocking)', () => {
        it('flags a tools/<id>/ directory present in the bundle but not in spec.tools[]', async () => {
            // The exact failure mode the concierge stumbles into when it
            // writes the source.ts + schema.json but skips adding the
            // {kind: "custom"} ref. We catch it before freeze so the user
            // can either add the ref or delete the dir.
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            await bundles.write('rev1', 'tools/incidentio-list-schedules/schema.json', '{}')
            await bundles.write('rev1', 'tools/incidentio-list-schedules/source.ts', 'export default ...')
            const report = await validateRevisionBundle(mkRev(), bundles)
            // Errors stay empty — freeze isn't blocked.
            expect(report.errors).toEqual([])
            expect(report.ok).toBe(true)
            expect(report.warnings).toEqual([
                {
                    code: 'orphan_custom_tool_dir',
                    message: expect.stringContaining('tools/incidentio-list-schedules/'),
                    pointer: 'tools/incidentio-list-schedules/',
                },
            ])
        })

        it('no warning when the orphan dir IS referenced by a custom tool spec entry', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            await bundles.write('rev1', 'tools/my-tool/schema.json', '{}')
            // Valid TS so the source check passes. compiled.js gets written
            // by the freeze step, not by the author — so we don't write it
            // here.
            await bundles.write('rev1', 'tools/my-tool/source.ts', 'export default async function run() { return {} }')
            const report = await validateRevisionBundle(
                mkRev({
                    tools: [{ kind: 'custom', id: 'my-tool', path: 'tools/my-tool' }],
                }),
                bundles
            )
            expect(report.warnings).toEqual([])
        })

        it('source.ts without a schema.json is NOT flagged (runner loads on schema, not source)', async () => {
            // Mirrors the runner's loader semantics — a stray source.ts
            // alone isn't a "tool", so it shouldn't get flagged. Otherwise
            // every test fixture that drops a half-written source would
            // spam warnings.
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            await bundles.write('rev1', 'tools/in-progress/source.ts', 'export default ...')
            const report = await validateRevisionBundle(mkRev(), bundles)
            expect(report.warnings).toEqual([])
        })

        it('flags a SKILL.md present in the bundle but not in spec.skills[]', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            await bundles.write('rev1', 'skills/research/SKILL.md', '# research')
            const report = await validateRevisionBundle(mkRev(), bundles)
            expect(report.errors).toEqual([])
            expect(report.warnings).toEqual([
                {
                    code: 'orphan_skill_file',
                    message: expect.stringContaining('skills/research/SKILL.md'),
                    pointer: 'skills/research/SKILL.md',
                },
            ])
        })

        it('flags a flat skills/foo.md when not in spec.skills[]', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            await bundles.write('rev1', 'skills/research.md', '# research')
            const report = await validateRevisionBundle(mkRev(), bundles)
            expect(report.warnings).toEqual([
                {
                    code: 'orphan_skill_file',
                    message: expect.stringContaining('skills/research.md'),
                    pointer: 'skills/research.md',
                },
            ])
        })

        it('does not flag a skill that IS referenced', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            await bundles.write('rev1', 'skills/research.md', '# research')
            const report = await validateRevisionBundle(
                mkRev({
                    skills: [{ id: 'research', path: 'skills/research.md' }],
                }),
                bundles
            )
            expect(report.warnings).toEqual([])
        })

        it('warnings and errors coexist — an orphan tool dir + a missing skill report both', async () => {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            await bundles.write('rev1', 'tools/forgotten/schema.json', '{}')
            await bundles.write('rev1', 'tools/forgotten/source.ts', 'export default ...')
            const report = await validateRevisionBundle(
                mkRev({
                    skills: [{ id: 'ghost', path: 'skills/missing.md' }],
                }),
                bundles
            )
            expect(report.errors).toEqual([
                {
                    code: 'missing_skill',
                    message: expect.stringContaining('skills/missing.md'),
                    pointer: 'spec.skills[0].path',
                },
            ])
            expect(report.warnings).toEqual([
                {
                    code: 'orphan_custom_tool_dir',
                    message: expect.stringContaining('tools/forgotten/'),
                    pointer: 'tools/forgotten/',
                },
            ])
            expect(report.ok).toBe(false)
        })
    })

    it('reports no_triggers when spec.triggers is empty', async () => {
        const bundles = makeBundles()
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
        const bundles = makeBundles()
        await bundles.write('rev1', 'agent.md', 'hi')
        const rev = mkRev()
        rev.state = 'ready'
        const report = await validateRevisionBundle(rev, bundles)
        expect(report.revision_state).toBe('ready')
        expect(report.revision_id).toBe('rev1')
    })

    describe('cron triggers', () => {
        const cronTrigger = (
            overrides: Record<string, unknown> = {}
        ): NonNullable<z.input<typeof AgentSpecSchema>['triggers']>[number] => ({
            type: 'cron',
            config: {
                name: 'digest',
                schedule: '0 9 * * MON',
                prompt: 'Produce the weekly digest for {fired_at:date}.',
                ...overrides,
            },
        })

        async function setup(
            triggers: Array<NonNullable<z.input<typeof AgentSpecSchema>['triggers']>[number]>
        ): ReturnType<typeof validateRevisionBundle> {
            const bundles = makeBundles()
            await bundles.write('rev1', 'agent.md', 'hi')
            return validateRevisionBundle(mkRev({ triggers }), bundles)
        }

        it('passes a well-formed cron trigger', async () => {
            const report = await setup([cronTrigger()])
            expect(report.ok).toBe(true)
            expect(report.errors).toEqual([])
        })

        it('flags a malformed cron schedule', async () => {
            const report = await setup([cronTrigger({ schedule: '0 25 * * MON' })])
            const codes = report.errors.map((e) => e.code)
            expect(codes).toContain('invalid_cron_schedule')
        })

        it('flags a sub-minute schedule that fires more than once a minute', async () => {
            const report = await setup([cronTrigger({ schedule: '* * * * * *' })])
            const codes = report.errors.map((e) => e.code)
            expect(codes).toContain('cron_schedule_too_frequent')
        })

        it('accepts an every-minute schedule (the 60s boundary)', async () => {
            const report = await setup([cronTrigger({ schedule: '* * * * *' })])
            const codes = report.errors.map((e) => e.code)
            expect(codes).not.toContain('cron_schedule_too_frequent')
        })

        it('flags an unknown IANA timezone', async () => {
            const report = await setup([cronTrigger({ timezone: 'Mars/Olympus_Mons' })])
            const codes = report.errors.map((e) => e.code)
            expect(codes).toContain('invalid_cron_timezone')
        })

        it('accepts a known IANA timezone with DST', async () => {
            const report = await setup([cronTrigger({ timezone: 'US/Pacific' })])
            expect(report.ok).toBe(true)
        })

        it('flags duplicate cron names within the same triggers[]', async () => {
            const report = await setup([
                cronTrigger({ name: 'digest', schedule: '0 9 * * MON' }),
                cronTrigger({ name: 'digest', schedule: '0 9 * * FRI' }),
            ])
            const codes = report.errors.map((e) => e.code)
            expect(codes).toContain('duplicate_cron_name')
        })

        it('flags an unknown placeholder in the prompt', async () => {
            const report = await setup([cronTrigger({ prompt: 'Run the digest for {unknown_placeholder}.' })])
            const err = report.errors.find((e) => e.code === 'unknown_cron_placeholder')
            expect(err).not.toBeUndefined()
            expect(err?.message).toContain('unknown_placeholder')
            expect(err?.pointer).toBe('spec.triggers[0].config.prompt')
        })

        it('flags an unknown placeholder in external_key', async () => {
            const report = await setup([cronTrigger({ external_key: 'digest-{run_id}' })])
            const err = report.errors.find((e) => e.code === 'unknown_cron_placeholder')
            expect(err).not.toBeUndefined()
            expect(err?.message).toContain('run_id')
            expect(err?.pointer).toBe('spec.triggers[0].config.external_key')
        })

        it('accepts every whitelisted placeholder', async () => {
            const report = await setup([
                cronTrigger({
                    prompt: 'cron={cron_name} schedule={schedule} iso={fired_at:iso} date={fired_at:date} week={fired_at:week}',
                    external_key: 'k-{fired_at:week}-{cron_name}',
                }),
            ])
            expect(report.ok).toBe(true)
        })
    })
})
