import type { HeatmapFilters } from 'lib/components/heatmaps/types'

import { HeatmapCoverageRow, HeatmapUrlDiagnosis, diagnoseEmptyHeatmap } from './heatmapCoverage'

const FILTERS: HeatmapFilters = { enabled: true, type: 'click', viewportAccuracy: 0.9 }
const NO_URL_DATA: HeatmapUrlDiagnosis = { sameUrlAnyDateCount: 0, pageAnyQueryCount: 0, similarUrls: [] }

describe('heatmapCoverage', () => {
    it.each<{
        name: string
        rows: HeatmapCoverageRow[]
        captureEnabled?: boolean
        urlDiagnosis?: HeatmapUrlDiagnosis | null
        expected: Record<string, unknown>
    }>([
        {
            name: 'points at the busiest preset when the data sits at a narrower width',
            rows: [
                { type: 'click', width: 384, count: 60 },
                { type: 'click', width: 400, count: 30 },
                { type: 'click', width: 1920, count: 10 },
            ],
            expected: { reason: 'other_widths', width: 375, share: 0.9 },
        },
        {
            name: 'blames the other filters when the selected width has data',
            rows: [{ type: 'click', width: 1000, count: 5 }],
            expected: { reason: 'other_filters' },
        },
        {
            name: 'suggests the interaction type that has data',
            rows: [
                { type: 'mousemove', width: 400, count: 40 },
                { type: 'rageclick', width: 400, count: 2 },
            ],
            expected: { reason: 'other_types', type: 'mousemove', count: 40 },
        },
        {
            name: 'suggests a longer date range before anything about the URL',
            rows: [],
            urlDiagnosis: { sameUrlAnyDateCount: 12, pageAnyQueryCount: 500, similarUrls: [] },
            expected: { reason: 'other_dates', count: 12 },
        },
        {
            name: 'finds the page under other query strings',
            rows: [],
            urlDiagnosis: { sameUrlAnyDateCount: 0, pageAnyQueryCount: 500, similarUrls: [] },
            expected: { reason: 'other_query_strings', count: 500 },
        },
        {
            name: 'lists similar URLs when the page itself has nothing',
            rows: [],
            urlDiagnosis: { ...NO_URL_DATA, similarUrls: [{ url: 'https://example.com/pricing/teams', count: 9 }] },
            expected: { reason: 'similar_urls', urls: [{ url: 'https://example.com/pricing/teams', count: 9 }] },
        },
        {
            name: 'reports no data when nothing matches anywhere',
            rows: [],
            urlDiagnosis: NO_URL_DATA,
            expected: { reason: 'no_data' },
        },
        {
            name: 'reports capture being off ahead of every other reason',
            rows: [{ type: 'click', width: 384, count: 60 }],
            captureEnabled: false,
            expected: { reason: 'capture_off' },
        },
    ])('$name', ({ rows, captureEnabled = true, urlDiagnosis = null, expected }) => {
        expect(
            diagnoseEmptyHeatmap({
                captureEnabled,
                rows,
                type: 'click',
                heatmapFilters: FILTERS,
                analysisWidth: 1024,
                urlDiagnosis,
            })
        ).toEqual(expected)
    })
})
