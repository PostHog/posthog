import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { InsightActorsView } from 'products/product_analytics/mcp/apps/InsightActorsView'
import type { InsightActorsData } from 'products/product_analytics/mcp/apps/insightActorsTransforms'

import { Component } from '@/ui-apps/components/Component'
import { insightResults, queryPayload } from '../fixtures/insight-fixtures'

// Server-side render smoke tests for the query-results dispatcher and the insight-actors
// view, fed with the same captured API payloads the unit tests use. renderToString runs
// the full component tree (minus effects), so a visualizer that throws on real data —
// e.g. calling `.map` on something that isn't an array — fails here instead of blanking
// the iframe in production.

describe('query-results Component rendering', () => {
    it.each([
        ['trends line', queryPayload(insightResults.trendsLine, 'TrendsQuery'), 'Trends'],
        ['trends line with breakdown', queryPayload(insightResults.trendsLineBreakdown, 'TrendsQuery'), 'Trends'],
        ['bold-number trends', queryPayload(insightResults.trendsNumber, 'TrendsQuery'), 'Trends'],
        ['pie-display trends', queryPayload(insightResults.trendsPie, 'TrendsQuery'), 'Trends'],
        ['world-map trends', queryPayload(insightResults.trendsWorldMap, 'TrendsQuery'), 'Trends'],
        ['stickiness', queryPayload(insightResults.stickiness, 'StickinessQuery'), 'Trends'],
        ['lifecycle', queryPayload(insightResults.lifecycle, 'LifecycleQuery'), 'Lifecycle'],
        ['flat funnel', queryPayload(insightResults.funnelTopToBottom, 'FunnelsQuery'), 'Funnel'],
        ['breakdown funnel', queryPayload(insightResults.funnelTopToBottomBreakdown, 'FunnelsQuery'), 'Funnel'],
        ['retention', queryPayload(insightResults.retention, 'RetentionQuery'), 'Retention'],
        ['paths', queryPayload(insightResults.userPaths, 'PathsQuery'), 'Paths'],
        ['hogql table', queryPayload(insightResults.hogqlTable, 'HogQLQuery'), 'Query results'],
    ] as const)('renders %s without crashing', (_label, payload, headerText) => {
        const html = renderToString(<Component data={payload} />)

        expect(html).toContain(headerText)
    })

    it.each([
        ['trends', 'TrendsQuery'],
        ['funnel', 'FunnelsQuery'],
        ['lifecycle', 'LifecycleQuery'],
        ['retention', 'RetentionQuery'],
        ['paths', 'PathsQuery'],
        ['hogql table', 'HogQLQuery'],
    ] as const)('renders empty %s results without crashing', (_label, kind) => {
        const html = renderToString(<Component data={queryPayload([], kind)} />)

        expect(html.length).toBeGreaterThan(0)
    })

    it('renders the unsupported state for unclassifiable data', () => {
        const html = renderToString(<Component data={{ results: [{ foo: 'bar' }] }} />)

        expect(html).toContain('supported in this view')
    })

    it('crashes on the formatted-string results insight-query currently sends', () => {
        // BUG PIN: insight-query with output_format=optimized (the default) puts a formatted
        // string into `results`; the kind fallback dispatches to TrendsVisualizer, which then
        // throws on `results.map`. AppWrapper has no error boundary, so the iframe goes blank.
        // Flip to a non-crashing assertion when insight-query adopts the wrapper pattern
        // and/or AppWrapper gets an error boundary.
        const payload = queryPayload('Date | $pageview\n2025-06-01 | 10', 'TrendsQuery')

        expect(() => renderToString(<Component data={payload} />)).toThrow(/is not a function/)
    })

    it('crashes on time-to-convert funnel results (bins object)', () => {
        // BUG PIN: the `{ bins }` object falls through the shape checks, the FunnelsQuery kind
        // dispatches it to FunnelVisualizer, and normalizeFunnelSteps throws on a non-array.
        const payload = queryPayload(insightResults.funnelTimeToConvert, 'FunnelsQuery')

        expect(() => renderToString(<Component data={payload} />)).toThrow(/is not a function/)
    })
})

describe('InsightActorsView rendering', () => {
    const actorsData = {
        query: {},
        results: {
            columns: ['distinct_id', 'email', 'event_count'],
            results: [['d1', 'a@b.com', 7]],
        },
        hasMore: false,
        offset: 0,
    } satisfies InsightActorsData

    it('renders actor rows from a query response', () => {
        const html = renderToString(<InsightActorsView data={actorsData} openLink={() => {}} />)

        expect(html).toContain('a@b.com')
    })

    it('renders empty results without crashing', () => {
        const empty = {
            query: {},
            results: { columns: [], results: [] },
            hasMore: false,
            offset: 0,
        } satisfies InsightActorsData

        const html = renderToString(<InsightActorsView data={empty} openLink={() => {}} />)

        expect(html.length).toBeGreaterThan(0)
    })
})
