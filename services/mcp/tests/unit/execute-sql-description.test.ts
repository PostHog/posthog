import { describe, expect, it } from 'vitest'

import { type ExecToolState, InstructionsBuilder } from '@/hono/instructions'
import CATALOG_TRUST_DISCOVERY from '@/templates/sections/catalog-trust-discovery.md'
import METRIC_DISCOVERY from '@/templates/sections/metric-discovery.md'

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

    it('swaps the metric rule for the save offer when a project has no saved metrics', () => {
        const rendered = builder.formatExecuteSqlDescription({
            metricCatalog: { count: 0 },
        } as unknown as ExecToolState)

        expect(rendered).not.toContain('The first call for that shape is `metric-list`')
        expect(rendered).toContain('This project has no saved metrics, so skip `metric-list`.')
        expect(rendered).toContain('#### Regular schema discovery')
    })

    // The description ships to every MCP client on every tools/list; keep the catalog
    // addition small so prompt bloat shows up as a reviewable failure, not silent growth.
    // Budget 3100 covers the metric-discovery section (carrying the catalog-vs-query-*
    // precedence rule, the search-first rule, synonym/derived-form and definition-question routing, the
    // plain-language one-off caveat the answer owes the reader, the trust badges, and the no-match offer
    // to save a settled measure as a proposed metric) plus the certification/verified-join
    // trust checklist; keep future additions under this so bloat still fails the build.
    it('keeps data-catalog discovery within its character budget', () => {
        const catalogSections = `${METRIC_DISCOVERY.trim()}\n\n${CATALOG_TRUST_DISCOVERY.trim()}`
        expect(catalogSections.length).toBeLessThan(3100)
    })
})
