import guidelines from '@shared/guidelines.md'
import { describe, expect, it } from 'vitest'

import { MCP_EXEC_SKILLS_FEATURE_FLAG } from '@/hono/constants'
import { InstructionsBuilder } from '@/hono/instructions'
import { buildMCPRequestContext } from '@/hono/mcp-context'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { MCPClientProfile } from '@/lib/client-detection'
import { estimateTokens } from '@/lib/estimate-tokens'
import { HOGQL_GUIDE_ID } from '@/lib/instructions-formatter'
import { parseRequestProperties } from '@/lib/request-properties'
import EXECUTE_SQL_REFERENCE from '@/templates/execute-sql-reference.md'
import CATALOG_TRUST_DISCOVERY from '@/templates/sections/catalog-trust-discovery.md'
import METRIC_DISCOVERY from '@/templates/sections/metric-discovery.md'

import { makeToolExecutorState } from '../shared/test-utils'

const GUIDELINES = '#### HogQL guidelines\n\nFull guideline text.'

function execState(
    opts: { consumer?: string; vendorClient?: string; skills?: boolean; headers?: Record<string, string> } = {}
): ResolvedState {
    return makeToolExecutorState([{ name: 'execute-sql' }], {
        useSingleExec: true,
        clientProfile: new MCPClientProfile({ vendorClient: opts.vendorClient }),
        requestContext: opts.headers
            ? buildMCPRequestContext(
                  parseRequestProperties(new Request('https://mcp.example.com/mcp', { headers: opts.headers }), {})
              )
            : ({ mcpConsumer: opts.consumer } as any),
        toolFeatureFlags: opts.skills ? { [MCP_EXEC_SKILLS_FEATURE_FLAG]: true } : {},
    })
}

describe('formatExecuteSqlDescription', () => {
    const builder = new InstructionsBuilder('some guidelines')

    it('includes data-catalog discovery', () => {
        const rendered = builder.formatExecuteSqlDescription()
        expect(rendered).toContain('#### Catalog trust signals')
        expect(rendered).toContain('certification')
        expect(rendered).toContain('confidence')
        expect(rendered).toContain('reasoning')
        expect(rendered).toContain('#### Metric discovery (semantic layer)')
        expect(rendered).toContain('metric-list')
        expect(rendered).toContain('metric-describe')
        expect(rendered).toContain('data-catalog-metric-run')
        expect(rendered).toContain('#### Regular schema discovery')
        // The tool's own intro must stay first; metric discovery sits after the
        // query-* routing section but keeps catalog-first precedence over raw
        // schema discovery.
        expect(rendered.startsWith('Executes HogQL')).toBe(true)
        const metricRoutingPosition = rendered.indexOf('#### Metric discovery (semantic layer)')
        expect(metricRoutingPosition).toBeGreaterThan(rendered.indexOf('### When to use `execute-sql`'))
        expect(metricRoutingPosition).toBeLessThan(rendered.indexOf('#### Regular schema discovery'))
    })

    // The description ships to every MCP client on every tools/list; keep the catalog
    // addition small so prompt bloat shows up as a reviewable failure, not silent growth.
    // Budget 3000 covers the metric-discovery section (carrying the catalog-vs-query-*
    // precedence rule, synonym/derived-form and definition-question routing, the
    // plain-language one-off caveat the answer owes the reader, the trust badges, and the no-match offer
    // to save a settled measure as a proposed metric) plus the certification/verified-join
    // trust checklist; keep future additions under this so bloat still fails the build.
    it('keeps data-catalog discovery within its character budget', () => {
        const catalogSections = `${METRIC_DISCOVERY.trim()}\n\n${CATALOG_TRUST_DISCOVERY.trim()}`
        expect(catalogSections.length).toBeLessThan(3000)
    })

    it.each([
        { label: 'tools mode', state: undefined, pointer: undefined },
        { label: 'posthog-code', state: execState({ consumer: 'posthog-code', skills: true }), pointer: undefined },
        {
            label: 'posthog-code with bundled skills',
            state: execState({
                headers: { 'x-posthog-mcp-consumer': 'posthog-code', 'x-posthog-mcp-bundled-skills': 'true' },
            }),
            pointer: 'bundled `querying-posthog-data` skill',
        },
        {
            label: 'plugin',
            state: execState({ consumer: 'plugin', skills: true }),
            pointer: 'bundled `querying-posthog-data` skill',
        },
        { label: 'cli without skills', state: execState(), pointer: `learn ${HOGQL_GUIDE_ID}` },
        { label: 'cli with skills', state: execState({ skills: true }), pointer: `learn ${HOGQL_GUIDE_ID}` },
        {
            label: 'claude web',
            state: execState({ vendorClient: 'ClaudeAI', skills: true }),
            pointer: `learn ${HOGQL_GUIDE_ID}`,
        },
    ])('serves the HogQL guidelines inline or names where to load them ($label)', ({ state, pointer }) => {
        const rendered = new InstructionsBuilder(GUIDELINES).formatExecuteSqlDescription(state)
        expect(rendered.includes(GUIDELINES)).toBe(pointer === undefined)
        expect(rendered).toContain(pointer ?? EXECUTE_SQL_REFERENCE.trim())
    })

    it('keeps the compact description within its token budget', () => {
        const rendered = new InstructionsBuilder(guidelines).formatExecuteSqlDescription(execState({ skills: true }))
        expect(estimateTokens(rendered)).toBeLessThan(4500)
    })

    it('loses no line of the full description between the compact variant and the hogql guide', async () => {
        const state = execState({ vendorClient: 'ClaudeAI' })
        const builder = new InstructionsBuilder(GUIDELINES)
        const full = builder.formatExecuteSqlDescription()
        const compact = builder.formatExecuteSqlDescription(state)
        const guide = await builder.buildExecLearnCatalog(state, undefined)!.execute(HOGQL_GUIDE_ID)

        const missing = full
            .split('\n')
            .filter((line) => line.trim() && !compact.includes(line) && !guide.includes(line))
        expect(missing).toEqual([])
    })
})
