import { describe, expect, it } from 'vitest'

import type { GroupType } from '@/api/client'
import { MCP_INSTRUCTIONS_CHAR_BUDGET } from '@/lib/constants'
import { buildToolDomainsCompact, type QueryToolInfo } from '@/lib/instructions'
import { InstructionsFormatter, type InstructionsContext } from '@/lib/instructions-formatter'

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

        it('always includes the agent-feedback section', () => {
            const formatter = new InstructionsFormatter()
            expect(formatter.buildToolsInstructions(fullCtx)).toContain('### Sharing feedback on PostHog')
            expect(formatter.buildToolsInstructions({ guidelines: 'rules' })).toContain(
                '### Sharing feedback on PostHog'
            )
        })
    })

    describe('buildExecInstructions', () => {
        it('renders the compact instructions section with placeholders resolved', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecInstructions(fullCtx)
            // query-* tools surface as the single `query` domain, not a separate catalog line
            expect(result).toContain('dashboard|execute-sql|feature-flag|query')
            expect(result).not.toContain('query-*:')
            // Env context is not here — it rides the exec command description, which has no
            // truncation cap, leaving this payload's whole budget to the domain index.
            expect(result).not.toContain('Defined group types: organization')
            expect(result).not.toContain("The user's name is Jane Doe")
            expect(result).not.toMatch(
                /\{tool_domains\}|\{query_tools\}|\{metadata\}|\{defined_groups\}|\{guidelines\}/
            )
        })

        // Synthetic fixture: 60 uniform `domain-N-get` names collapse to short domains and
        // cost ~1/3 of what the live catalog does, which is how a 2,923-char payload shipped
        // past a passing 2048 assertion. Kept for the placeholder wiring it exercises; the
        // assertion that actually guards the cap runs the real catalog, in
        // `instructions-formatter-snapshot.test.ts`.
        it('stays under the character budget at synthetic tool counts', () => {
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
            expect(result.length).toBeLessThanOrEqual(MCP_INSTRUCTIONS_CHAR_BUDGET)
        })

        // The domain index names PostHog resources, not callable tools, so without this
        // line the payload never states what can actually be called. `render-ui` is only
        // mounted on MCP Apps hosts — naming it elsewhere advertises a tool that isn't there.
        it('names the callable tools, gating render-ui on the host mounting it', () => {
            const formatter = new InstructionsFormatter()
            const withUi = formatter.buildExecInstructions({ ...fullCtx, renderUiEnabled: true })
            const withoutUi = formatter.buildExecInstructions({ ...fullCtx, renderUiEnabled: false })

            expect(withUi).toContain('exec – run any PostHog command')
            expect(withUi).toContain('render-ui – show a tool result as an interactive app.')
            expect(withoutUi).toContain('exec – run any PostHog command')
            expect(withoutUi).not.toContain('render-ui')
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
            expect(result).toContain('Run `info <tool_name>` once if its schema is not in context.')
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

        it('always includes the agent-feedback section', () => {
            const formatter = new InstructionsFormatter()
            for (const stripEnvContext of [true, false]) {
                const withFeedback = formatter.buildExecCommandReference(fullCtx, { stripEnvContext })
                expect(withFeedback).toContain('### Sharing feedback on PostHog')
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
    })

    describe('Claude web/desktop exec guidance', () => {
        it('keeps routine guidance inline and advertises optional topics', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildClaudeExecCommandReference(fullCtx)

            expect(result).toContain('**LEARN FIRST: HARD REQUIREMENT**')
            expect(result).toContain('learn <topic...> - load one or more learning topics')
            expect(result).toContain('Topics are cumulative.')
            expect(result).toContain('User: create pageviews visualization')
            expect(result).toContain(
                "Assistant: This needs analytics and visualization guidance, so I'll load both first."
            )
            expect(result).toContain('posthog:exec({"command":"learn analytics visualizations"})')
            expect(result).toContain('User: How many weekly active users do we have?')
            expect(result).toContain('render-ui({ "tool_name": "query-trends", "tool_input": {...} })')
            expect(result.indexOf('render-ui({ "tool_name": "query-trends"')).toBeGreaterThan(
                result.indexOf('posthog:exec({"command":"call query-trends {...}"})')
            )
            expect(result).toContain('- analytics:')
            expect(result).toContain('- visualizations:')
            expect(result).toContain('- urls:')
            expect(result).toContain('- feedback:')
            expect(result).toContain('SCHEMA DRILL-DOWN RULE')
            expect(result).toContain('**Data discovery:**')
            expect(result).toContain('**CORRECT usage pattern:**')
            expect(result.indexOf('User: create pageviews visualization')).toBeGreaterThan(
                result.indexOf('**CORRECT usage pattern:**')
            )
            expect(result).toContain('### Basic functionality')
            expect(result).toContain('### Tool search')
            expect(result).toContain(buildToolDomainsCompact(realisticTools))
            expect(result).toContain("The user's name is Jane Doe")
            expect(result).toContain('Defined group types: organization')
            expect(result).not.toContain('### Retrieving data')
            expect(result).not.toContain('### Examples')
            expect(result).not.toContain('### Rendering visualizations')
            expect(result).not.toContain('### URL patterns')
            expect(result).not.toContain('### Sharing feedback on PostHog')
            expect(result).not.toContain('- `query-trends` — time series')
            expect(result).not.toMatch(/\{help_topics\}|\{query_tools\}|\{metadata\}|\{defined_groups\}|\{guidelines\}/)
        })

        it('builds optional learning topics from their full guidance', () => {
            const formatter = new InstructionsFormatter()
            const entries = formatter.buildClaudeExecHelpEntries(fullCtx)
            const analytics = entries.find((entry) => entry.id === 'analytics')

            expect(entries.map(({ id, kind }) => ({ id, kind }))).toEqual([
                { id: 'analytics', kind: 'guide' },
                { id: 'visualizations', kind: 'guide' },
                { id: 'urls', kind: 'guide' },
                { id: 'feedback', kind: 'guide' },
            ])
            expect(analytics?.content).toContain('### Retrieving data')
            expect(analytics?.content).toContain('### Examples')
            expect(analytics?.content).toContain('- `query-trends` — time series')
            expect(entries.find((entry) => entry.id === 'visualizations')?.content).toContain(
                '### Rendering visualizations'
            )
            expect(entries.find((entry) => entry.id === 'urls')?.content).toContain('### URL patterns')
            expect(entries.find((entry) => entry.id === 'feedback')?.content).toContain(
                '### Sharing feedback on PostHog'
            )
        })

        it('only advertises visualizations when rendering is available', () => {
            const formatter = new InstructionsFormatter()
            const ctx = {
                ...fullCtx,
                renderUiEnabled: false,
            }

            expect(formatter.buildClaudeExecHelpEntries(ctx).map((entry) => entry.id)).toEqual([
                'analytics',
                'urls',
                'feedback',
            ])
            const result = formatter.buildClaudeExecCommandReference(ctx)
            expect(result).toContain('- analytics:')
            expect(result).not.toContain('- visualizations:')
            expect(result).toContain('- urls:')
            expect(result).toContain('- feedback:')
        })
    })

    describe('metric discovery gating (data catalog flag)', () => {
        const surfaces: {
            name: string
            render: (formatter: InstructionsFormatter, ctx: InstructionsContext) => string
            mustPrecede: string[]
        }[] = [
            {
                name: 'buildToolsInstructions',
                render: (formatter, ctx) => formatter.buildToolsInstructions(ctx),
                mustPrecede: ['### Retrieving data', '#### Schema-first workflow'],
            },
            {
                name: 'analytics learn topic content',
                render: (formatter, ctx) =>
                    formatter.buildClaudeExecHelpEntries(ctx).find((entry) => entry.id === 'analytics')!.content,
                mustPrecede: ['### Retrieving data', '#### Schema-first workflow'],
            },
            {
                name: 'buildExecCommandReference',
                render: (formatter, ctx) => formatter.buildExecCommandReference(ctx, { stripEnvContext: false }),
                mustPrecede: ['SCHEMA DRILL-DOWN RULE', '### Retrieving data'],
            },
        ]

        it.each(surfaces)(
            '$name puts gated metric routing before generic analytics guidance',
            ({ render, mustPrecede }) => {
                const formatter = new InstructionsFormatter()
                const flagOn = render(formatter, { ...fullCtx, dataCatalogEnabled: true })
                const metricRoutingPosition = flagOn.indexOf('#### Metric discovery (semantic layer)')
                expect(metricRoutingPosition).toBeGreaterThanOrEqual(0)
                expect(flagOn).toContain('system.information_schema.metrics')
                expect(flagOn).toContain('data-catalog-metric-run')
                for (const genericGuidance of mustPrecede) {
                    expect(metricRoutingPosition).toBeLessThan(flagOn.indexOf(genericGuidance))
                }

                // Flag-off must be byte-identical to a context without the field, so orgs
                // without the catalog are never steered at a table that doesn't exist.
                const flagOff = render(formatter, { ...fullCtx, dataCatalogEnabled: false })
                expect(flagOff).not.toContain('#### Metric discovery')
                expect(flagOff).toBe(render(formatter, fullCtx))
            }
        )

        it('advertises governed metrics in the analytics topic description only when the catalog exists', () => {
            const formatter = new InstructionsFormatter()
            const analyticsDescription = (ctx: InstructionsContext): string =>
                formatter.buildClaudeExecHelpEntries(ctx).find((entry) => entry.id === 'analytics')!.description
            expect(analyticsDescription({ ...fullCtx, dataCatalogEnabled: true })).toContain('governed metrics')
            expect(analyticsDescription(fullCtx)).toBe('Query or analyze PostHog data, metrics, and events.')
        })
    })

    describe('analysis artifact guidance', () => {
        const surfaces: {
            name: string
            render: (formatter: InstructionsFormatter, ctx: InstructionsContext) => string
        }[] = [
            {
                name: 'buildToolsInstructions',
                render: (formatter, ctx) => formatter.buildToolsInstructions(ctx),
            },
            {
                name: 'analytics learn topic content',
                render: (formatter, ctx) =>
                    formatter.buildClaudeExecHelpEntries(ctx).find((entry) => entry.id === 'analytics')!.content,
            },
            {
                name: 'buildExecCommandReference',
                render: (formatter, ctx) => formatter.buildExecCommandReference(ctx, { stripEnvContext: false }),
            },
        ]

        it.each(surfaces)('$name routes deep dives to notebooks and tracking to dashboards', ({ render }) => {
            const formatter = new InstructionsFormatter()
            const result = render(formatter, fullCtx)
            expect(result).toContain('### Where an analysis lands')
            expect(result).toContain('**Notebook**')
            expect(result).toContain('**Dashboard**')
        })

        // The Python guidance names `notebooks-add-cell`, so it must stay out of prompts
        // for clients that aren't advertised the cell tools.
        it.each(surfaces)('$name gates the Python section on the notebook cell tools', ({ render }) => {
            const formatter = new InstructionsFormatter()
            const cellsOn = render(formatter, { ...fullCtx, notebookCellsEnabled: true })
            expect(cellsOn).toContain('### Python in an analysis')
            expect(cellsOn).toContain("cell_type: 'python'")

            const cellsOff = render(formatter, { ...fullCtx, notebookCellsEnabled: false })
            expect(cellsOff).not.toContain('### Python in an analysis')
            expect(cellsOff).toBe(render(formatter, fullCtx))
        })
    })

    // Mirrors the single-exec wiring in `src/mcp.ts`. When the client honors the MCP
    // `instructions` field, that payload carries exactly one thing — the tool-domain index
    // (including the `query` domain) — because clients hard-truncate it. Everything else,
    // env-context and the query-tool catalog included, stays on the `command` description,
    // which has no cap. Codex (no `instructions` support) keeps today's behavior: empty
    // `instructions`, everything inlined in the `command` description.
    describe('exec mode wiring', () => {
        it.each([
            { name: 'supportsInstructions=true (Claude Code etc.)', supportsInstructions: true },
            { name: 'supportsInstructions=false (Codex)', supportsInstructions: false },
        ])('$name: splits product context between instructions and commandReference', ({ supportsInstructions }) => {
            const formatter = new InstructionsFormatter()
            const instructions = supportsInstructions ? formatter.buildExecInstructions(fullCtx) : ''
            const commandReference = formatter.buildExecCommandReference(fullCtx, {
                stripEnvContext: supportsInstructions,
                keepEnvContext: true,
            })

            expect(commandReference).toContain('SCHEMA DRILL-DOWN RULE')
            expect(commandReference).toContain('### Basic functionality')
            // the query catalog always lives on the command reference, both modes
            expect(commandReference).toContain('- `query-trends` — time series')

            if (supportsInstructions) {
                // queries surface in instructions only as the `query` tool domain
                expect(instructions).toContain('dashboard|execute-sql|feature-flag|query')
                expect(instructions).not.toContain('- `query-trends` — time series')
                expect(instructions).not.toContain("The user's name is Jane Doe")
                expect(instructions).not.toContain('Defined group types: organization')
                expect(commandReference).toContain("The user's name is Jane Doe")
                expect(commandReference).toContain('Defined group types: organization')
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
