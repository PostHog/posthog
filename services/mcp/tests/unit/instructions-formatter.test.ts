import { afterEach, describe, expect, it } from 'vitest'

import type { GroupType } from '@/api/client'
import { InstructionsBuilder } from '@/hono/instructions'
import type { ResolvedState } from '@/hono/request-state-resolver'
import type { QueryToolInfo } from '@/lib/instructions'
import { InstructionsFormatter, type InstructionsContext } from '@/lib/instructions-formatter'
import { CODE_EXECUTION_FEATURE_FLAG } from '@/tools/code-exec/constants'

const realisticGroupTypes: GroupType[] = [
    { group_type: 'organization', group_type_index: 0, name_singular: null, name_plural: null },
]
// `tools` mirrors production: the full tool set, query-* included (the domain
// extractor collapses them into the single `query` domain). `queryTools` below
// is the parallel catalog projection with hints.
const realisticTools = [
    { name: 'dashboard-create', category: 'Dashboards' },
    { name: 'dashboard-get', category: 'Dashboards' },
    { name: 'feature-flag-create', category: 'Feature flags' },
    { name: 'feature-flag-get-all', category: 'Feature flags' },
    { name: 'execute-sql', category: 'SQL' },
    { name: 'query-trends', category: 'Query wrappers' },
    { name: 'query-funnel', category: 'Query wrappers' },
]
const realisticQueryTools: QueryToolInfo[] = [
    { name: 'query-trends', title: 'Trends', systemPromptHint: 'time series' },
    { name: 'query-funnel', title: 'Funnel', systemPromptHint: 'conversion rate' },
]
const realisticMetadata =
    'You are currently in project "My App" (id: 1, token: token_1) within organization "Acme" (id: org_1).\n' +
    'Project timezone: America/New_York.\n' +
    "The user's name is Jane Doe (jane@acme.com)."

const fullCtx: InstructionsContext = {
    guidelines: 'some guidelines',
    groupTypes: realisticGroupTypes,
    metadata: realisticMetadata,
    tools: realisticTools,
    queryTools: realisticQueryTools,
    featureFlags: { 'mcp-feedback-tool': true },
    renderUiEnabled: true,
}

describe('InstructionsFormatter', () => {
    describe('buildToolsInstructions', () => {
        it('resolves every placeholder when fully populated', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildToolsInstructions(fullCtx)
            expect(result).toContain('Defined group types: organization')
            expect(result).toContain("The user's name is Jane Doe")
            expect(result).toContain('Project timezone: America/New_York.')
            expect(result).toContain('- dashboard')
            expect(result).toContain('- feature-flag')
            expect(result).toContain('- execute-sql')
            expect(result).toContain('- `query-funnel` — conversion rate')
            expect(result).toContain('- `query-trends` — time series')
            expect(result).not.toMatch(
                /\{tool_domains\}|\{query_tools\}|\{metadata\}|\{defined_groups\}|\{guidelines\}/
            )
        })

        it('renders the basic functionality, retrieving data, and examples sections', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildToolsInstructions(fullCtx)
            expect(result).toContain('### Basic functionality')
            expect(result).toContain('### Retrieving data')
            expect(result).toContain('### Examples')
        })

        it('does not leak any CLI-only sections (tools mode is not exec mode)', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildToolsInstructions(fullCtx)
            expect(result).not.toContain('SCHEMA DRILL-DOWN RULE')
            expect(result).not.toContain('Using the `posthog` tool')
            expect(result).not.toContain('CLI-style command string')
        })

        it('omits placeholders cleanly when context fields are undefined', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildToolsInstructions({ guidelines: 'rules' })
            expect(result).not.toContain('{guidelines}')
            expect(result).not.toContain('{defined_groups}')
            expect(result).not.toContain('{tool_domains}')
            expect(result).not.toContain('{query_tools}')
            expect(result).not.toContain('{metadata}')
        })

        it('includes the agent-feedback section only when the mcp-feedback-tool flag is on', () => {
            const formatter = new InstructionsFormatter()
            const withFeedback = formatter.buildToolsInstructions(fullCtx)
            expect(withFeedback).toContain('### Sharing feedback on PostHog')

            for (const featureFlags of [undefined, { 'mcp-feedback-tool': false }, {}]) {
                const result = formatter.buildToolsInstructions({ ...fullCtx, featureFlags })
                expect(result).not.toContain('### Sharing feedback on PostHog')
            }
        })
    })

    describe('buildExecInstructions', () => {
        it('renders the compact instructions section with placeholders resolved', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecInstructions(fullCtx)
            // query-* tools surface as the single `query` domain, not a separate catalog line
            expect(result).toContain('dashboard|execute-sql|feature-flag|query')
            expect(result).not.toContain('query-*:')
            expect(result).toContain('Defined group types: organization')
            expect(result).toContain("The user's name is Jane Doe")
            expect(result).not.toMatch(
                /\{tool_domains\}|\{query_tools\}|\{metadata\}|\{defined_groups\}|\{guidelines\}/
            )
        })

        // Claude Code caps MCP `instructions` at 2048 chars — stay under the budget with
        // a realistic-ish tool count so this asserts something meaningful. 60 domains +
        // 12 query tools ≈ today's v2 deployment.
        it('stays under the 2048-character budget at realistic tool counts', () => {
            const manyTools = Array.from({ length: 60 }, (_, i) => ({
                name: `domain-${i}-get`,
                category: `Category ${i % 6}`,
            }))
            const manyQueryTools: QueryToolInfo[] = Array.from({ length: 12 }, (_, i) => ({
                name: `query-tool-${i}`,
                title: `Query tool ${i}`,
                systemPromptHint: `short hint for query tool ${i}`,
            }))
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecInstructions({
                guidelines: 'guidelines',
                groupTypes: realisticGroupTypes,
                metadata: realisticMetadata,
                tools: manyTools,
                queryTools: manyQueryTools,
            })
            expect(result.length).toBeLessThanOrEqual(2048)
        })

        it('does not bleed the full command reference into the compact instructions', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecInstructions(fullCtx)
            expect(result).not.toContain('SCHEMA DRILL-DOWN RULE')
            expect(result).not.toContain('### Basic functionality')
            expect(result).not.toContain('### Examples')
        })
    })

    describe('buildExecToolDescription', () => {
        it('renders just the exec tool blurb, no other sections', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecToolDescription()
            expect(result).toContain('Using the `posthog` tool')
            expect(result).toContain('MANDATORY — HARD REQUIREMENTS')
            expect(result).not.toContain('### Basic functionality')
            expect(result).not.toContain('### Examples')
        })
    })

    describe('buildExecCommandReference', () => {
        it('carries the CLI mechanics regardless of stripEnvContext', () => {
            const formatter = new InstructionsFormatter()
            for (const stripEnvContext of [true, false]) {
                const result = formatter.buildExecCommandReference(fullCtx, { stripEnvContext })
                expect(result).toContain('SCHEMA DRILL-DOWN RULE')
                expect(result).toContain('### Basic functionality')
                expect(result).toContain('### Examples')
            }
        })

        it('does not include the exec-tool blurb (that lives on the tool description)', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecCommandReference(fullCtx, { stripEnvContext: false })
            expect(result).not.toContain('Using the `posthog` tool')
        })

        it('embeds env-context and query-tool catalog when stripEnvContext is false', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecCommandReference(fullCtx, { stripEnvContext: false })
            expect(result).toContain("The user's name is Jane Doe")
            expect(result).toContain('Defined group types: organization')
            // Tool domains are temporarily omitted from the command reference while
            // probing claude.ai's per-tool size cap; discovery rides on `search`.
            expect(result).not.toContain('dashboard|execute-sql')
            expect(result).toContain('- `query-trends` — time series')
        })

        it('strips env-context and tool-domain list but keeps the query-tool catalog when stripEnvContext is true', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecCommandReference(fullCtx, { stripEnvContext: true })
            expect(result).not.toContain("The user's name is Jane Doe")
            expect(result).not.toContain('Defined group types: organization')
            // The query catalog stays on the exec command reference even when env is stripped.
            expect(result).toContain('- `query-trends` — time series')
            expect(result).not.toContain('dashboard|execute-sql')
        })

        it('keeps the env-context even when stripEnvContext is set, when keepEnvContext is set', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecCommandReference(fullCtx, {
                stripEnvContext: true,
                keepEnvContext: true,
            })
            // Project metadata and group types survive for clients (Claude
            // web/desktop) that ignore the `instructions` payload, so they still
            // reach the model via the command reference. Tool domains are
            // temporarily omitted (size-cap probe).
            expect(result).not.toContain('dashboard|execute-sql')
            expect(result).toContain("The user's name is Jane Doe")
            expect(result).toContain('Defined group types: organization')
        })

        it('includes the agent-feedback section only when the mcp-feedback-tool flag is on', () => {
            const formatter = new InstructionsFormatter()
            for (const stripEnvContext of [true, false]) {
                const withFeedback = formatter.buildExecCommandReference(fullCtx, { stripEnvContext })
                expect(withFeedback).toContain('### Sharing feedback on PostHog')

                const withoutFeedback = formatter.buildExecCommandReference(
                    { ...fullCtx, featureFlags: { 'mcp-feedback-tool': false } },
                    { stripEnvContext }
                )
                expect(withoutFeedback).not.toContain('### Sharing feedback on PostHog')
            }
        })

        it('includes the rendering section only when render-ui is available for the client', () => {
            const formatter = new InstructionsFormatter()
            for (const stripEnvContext of [true, false]) {
                const withRendering = formatter.buildExecCommandReference(fullCtx, { stripEnvContext })
                expect(withRendering).toContain('### Rendering visualizations')

                // The raw flag being on isn't enough — a non-UI-host client (e.g. Claude Code)
                // resolves `renderUiEnabled` to false and must not see the rendering section.
                const withoutRendering = formatter.buildExecCommandReference(
                    { ...fullCtx, renderUiEnabled: false },
                    { stripEnvContext }
                )
                expect(withoutRendering).not.toContain('### Rendering visualizations')
            }
        })

        // The advertised command set must match what the dispatcher accepts per
        // availability level (spec §4.2/§4.4): a fast-path-only server that
        // documented unrestricted scripts would steer agents into
        // sandbox-unavailable errors, and vice versa.
        it.each([
            {
                level: 'full' as const,
                contains: [
                    '### Code execution',
                    'types <query>',
                    'sql <hogql>',
                    'run <typescript source>',
                    'apply <plan-id>',
                    'top-level `await`',
                ],
                notContains: ['single-call scripts only'],
            },
            {
                level: 'fast-path' as const,
                contains: [
                    '### Code execution',
                    'types <query>',
                    'sql <hogql>',
                    'run <typescript source>',
                    'apply <plan-id>',
                    'single-call scripts only',
                ],
                notContains: ['top-level `await`'],
            },
            {
                level: 'off' as const,
                contains: [],
                notContains: ['### Code execution', 'types <query>', 'run <typescript source>'],
            },
            // `fullCtx` leaves the field unset — the sections must be opt-in.
            {
                level: undefined,
                contains: [],
                notContains: ['### Code execution', 'types <query>', 'run <typescript source>'],
            },
        ])('advertises the code-execution command set for level "$level"', ({ level, contains, notContains }) => {
            const formatter = new InstructionsFormatter()
            for (const stripEnvContext of [true, false]) {
                const result = formatter.buildExecCommandReference(
                    { ...fullCtx, codeExecution: level },
                    { stripEnvContext }
                )
                for (const expected of contains) {
                    expect(result).toContain(expected)
                }
                for (const unexpected of notContains) {
                    expect(result).not.toContain(unexpected)
                }
            }
        })

        describe('code-first arm (mcp-code-first, spec §4.6 Phase 3)', () => {
            const codeFirstCtx: InstructionsContext = { ...fullCtx, codeExecution: 'full', codeFirstEnabled: true }

            it('swaps the JSON-schema discovery prose for the script surface and keeps data-taxonomy prose', () => {
                const formatter = new InstructionsFormatter()
                const result = formatter.buildExecCommandReference(codeFirstCtx, { stripEnvContext: false })
                // Cut per spec §4.4: legacy verb table, drill-down protocol, tool
                // search, schema workflow, call transcripts, planning examples.
                expect(result).not.toContain('CLI-style command string')
                expect(result).not.toContain('SCHEMA DRILL-DOWN RULE')
                expect(result).not.toContain('### Tool search')
                expect(result).not.toContain('#### Schema-first workflow')
                expect(result).not.toContain('INCORRECT usage patterns')
                expect(result).not.toContain('### Examples')
                // The code-first surface in their place.
                expect(result).toContain('types <query | TypeName... | domain.method | domain>')
                expect(result).toContain('### SDK cheat sheet')
                expect(result).toContain('### Mutations: plan → confirm → apply')
                expect(result).toContain('sql <hogql>')
                // Data-taxonomy prose survives untouched (spec §4.4), including the
                // entity-schema-discovery placeholder and the query-tool catalog.
                expect(result).toContain('Data discovery:')
                expect(result).toContain('#### Searching for existing entities')
                expect(result).toContain('- `query-trends` — time series')
                // Template maintainer comments must never reach the prompt.
                expect(result).not.toContain('<!--')
            })

            // The arm documents unrestricted scripts as THE interface, so
            // anywhere the sandbox executor is absent (or the flag is off) the
            // legacy arm must keep serving — flipping `mcp-code-first` alone in
            // production would otherwise document capability the dispatcher
            // rejects (and disagree with the dispatcher's own gating).
            it.each([
                { name: 'flag off at full availability', ctx: { ...fullCtx, codeExecution: 'full' as const } },
                {
                    name: 'flag on without an executor (fast-path level)',
                    ctx: { ...fullCtx, codeExecution: 'fast-path' as const, codeFirstEnabled: true },
                },
                { name: 'flag on with code execution off', ctx: { ...fullCtx, codeFirstEnabled: true } },
            ])('$name keeps serving the legacy arm', ({ ctx }) => {
                const result = new InstructionsFormatter().buildExecCommandReference(ctx, { stripEnvContext: false })
                expect(result).toContain('SCHEMA DRILL-DOWN RULE')
                expect(result).not.toContain('### SDK cheat sheet')
            })

            it('gates the rendering section on renderUiEnabled exactly like the legacy arm', () => {
                const formatter = new InstructionsFormatter()
                expect(formatter.buildExecCommandReference(codeFirstCtx, { stripEnvContext: false })).toContain(
                    '### Rendering visualizations'
                )
                expect(
                    formatter.buildExecCommandReference(
                        { ...codeFirstCtx, renderUiEnabled: false },
                        { stripEnvContext: false }
                    )
                ).not.toContain('### Rendering visualizations')
            })

            it('switches the tool description to the code-first blurb only for a code-first context', () => {
                const formatter = new InstructionsFormatter()
                const codeFirstBlurb = formatter.buildExecToolDescription(codeFirstCtx)
                expect(codeFirstBlurb).toContain('@posthog/sdk')
                expect(codeFirstBlurb).not.toContain('MANDATORY — HARD REQUIREMENTS')
                // A non-code-first context (and the CLI's zero-arg call, covered
                // above) keeps the legacy blurb byte-for-byte.
                expect(formatter.buildExecToolDescription(fullCtx)).toBe(formatter.buildExecToolDescription())
            })
        })
    })

    // Mirrors the single-exec wiring in `src/mcp.ts`. When the client honors the MCP
    // `instructions` field, env-context moves out of the `command` description and into
    // `instructions`: tool domains (including the `query` domain), user preferences
    // (timezone/name via `{metadata}`), and defined group types. The query-tool catalog
    // stays on the `command` description. Codex (no `instructions` support) keeps today's
    // behavior: empty `instructions`, everything inlined in the `command` description.
    describe('exec mode wiring', () => {
        it.each([
            { name: 'supportsInstructions=true (Claude Code etc.)', supportsInstructions: true },
            { name: 'supportsInstructions=false (Codex)', supportsInstructions: false },
        ])('$name: splits product context between instructions and commandReference', ({ supportsInstructions }) => {
            const formatter = new InstructionsFormatter()
            const instructions = supportsInstructions ? formatter.buildExecInstructions(fullCtx) : ''
            const commandReference = formatter.buildExecCommandReference(fullCtx, {
                stripEnvContext: supportsInstructions,
            })

            expect(commandReference).toContain('SCHEMA DRILL-DOWN RULE')
            expect(commandReference).toContain('### Basic functionality')
            // the query catalog always lives on the command reference, both modes
            expect(commandReference).toContain('- `query-trends` — time series')

            if (supportsInstructions) {
                // queries surface in instructions only as the `query` tool domain
                expect(instructions).toContain('dashboard|execute-sql|feature-flag|query')
                expect(instructions).not.toContain('- `query-trends` — time series')
                expect(instructions).toContain("The user's name is Jane Doe")
                expect(instructions).toContain('Defined group types: organization')
                expect(commandReference).not.toContain("The user's name is Jane Doe")
                expect(commandReference).not.toContain('Defined group types: organization')
                expect(commandReference).not.toContain('dashboard|execute-sql')
            } else {
                expect(instructions).toBe('')
                expect(commandReference).toContain('- `query-trends` — time series')
                expect(commandReference).toContain("The user's name is Jane Doe")
                expect(commandReference).not.toContain('dashboard|execute-sql')
                expect(commandReference).toContain('Defined group types: organization')
            }
        })
    })
})

describe('InstructionsBuilder code-execution availability level (spec §4.4)', () => {
    const ORIG_NODE_ENV = process.env.NODE_ENV

    afterEach(() => {
        process.env.NODE_ENV = ORIG_NODE_ENV
    })

    const makeState = (flagOn: boolean): ResolvedState =>
        ({
            allTools: [],
            toolFeatureFlags: flagOn ? { [CODE_EXECUTION_FEATURE_FLAG]: true } : {},
            renderUiEnabled: false,
        }) as unknown as ResolvedState

    it.each([
        { case: 'flag off', flagOn: false, nodeEnv: 'test', level: 'off' },
        { case: 'flag on where the sandbox can run', flagOn: true, nodeEnv: 'test', level: 'full' },
        // In production no sandbox exists yet, so the flag documents `run`
        // restricted to single-call (fast-path) scripts, never unrestricted ones.
        { case: 'flag on where the sandbox cannot run', flagOn: true, nodeEnv: 'production', level: 'fast-path' },
    ])('$case resolves the "$level" level', ({ flagOn, nodeEnv, level }) => {
        process.env.NODE_ENV = nodeEnv
        const ctx = new InstructionsBuilder('guidelines').buildContext(makeState(flagOn))
        expect(ctx.codeExecution).toBe(level)
    })
})
