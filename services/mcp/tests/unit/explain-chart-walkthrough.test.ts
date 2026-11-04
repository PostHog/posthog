import { describe, expect, it } from 'vitest'

import type { ExplainChartData } from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'
import {
    anchorOf,
    chapterFacts,
    dateLabel,
    overviewFacts,
} from 'products/product_analytics/mcp/apps/explainChart/storyFacts'
import { placeMarkers } from 'products/product_analytics/mcp/apps/explainChart/storyMarkerPlacement'
import { isSeriesNamedIn } from 'products/product_analytics/mcp/apps/explainChart/storyNamedSeries'
import { buildStoryPages } from 'products/product_analytics/mcp/apps/explainChart/storyPages'

const DAYS = ['2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04', '2026-10-05']
const MARKER_LAYOUT = { radius: 10, distance: 22, bounds: { left: 0, top: 0, right: 400, bottom: 300 } }

describe('explain chart', () => {
    it('keeps a small rate from rounding to zero', () => {
        const facts = chapterFacts([0.02, 0.02, 0.02, 0.02, 0.02], DAYS, [1, 3], {
            interval: 'day',
            lastPointInProgress: false,
            formatValue: (value) => `${value * 100}%`,
        })

        expect(facts).toContain('2%')
        expect(facts).not.toContain('0%')
    })

    it('describes a series with more points than a function call can take', () => {
        const values = Array.from({ length: 200_000 }, (_, index) => index % 7)

        expect(
            overviewFacts(values, { interval: 'minute', lastPointInProgress: false, formatValue: String })
        ).toContain('The range runs from 0 to 6.')
    })

    it('counts a negative bucket as activity', () => {
        const facts = overviewFacts([1, -1, -1, 2, 3, -1], {
            interval: 'day',
            lastPointInProgress: false,
            formatValue: String,
        })

        expect(facts).not.toContain('Only')
    })

    it('keeps a per-second chart in seconds', () => {
        const seconds = ['2026-10-01 10:00:00', '2026-10-01 10:00:01', '2026-10-01 10:00:02', '2026-10-01 10:00:03']
        const facts = chapterFacts([1, 2, 3, 4], seconds, [1, 2], {
            interval: 'second',
            lastPointInProgress: false,
            formatValue: String,
        })

        expect(facts).toContain('typical second')
        expect(facts).toContain('10:00:01')
    })

    it('does not call a stretch empty when only its unfinished last point has activity', () => {
        const facts = chapterFacts([0, 0, 20], DAYS.slice(0, 3), [0, 2], {
            interval: 'day',
            lastPointInProgress: true,
            formatValue: String,
        })

        expect(facts).not.toContain('every value is zero')
    })

    it.each([
        ['a start below zero', [-1e20, 0]],
        ['a fractional index', [0.5, 1]],
        ['an end past the last point', [1, 3]],
    ])('shows a chapter with %s as one without a point', (_, range) => {
        const data = {
            query: { kind: 'TrendsQuery', interval: 'day', series: [] },
            results: [{ label: 'signed_up', data: [1, 2, 3], days: DAYS.slice(0, 3) }],
            seriesIndex: 0,
            insightName: 'Sign-ups',
            lastPointInProgress: false,
            headline: 'A headline.',
            chapters: [
                {
                    title: 'A chapter',
                    range,
                    summary: null,
                    cause: null,
                    confidence: null,
                    confidenceReason: null,
                    evidence: [],
                },
            ],
        } as unknown as ExplainChartData

        const [, chapter] = buildStoryPages(data, String)

        expect(chapter?.range).toBeNull()
        expect(chapter?.anchor).toBeNull()
    })

    it('does not compare a period that has not ended with complete ones', () => {
        const facts = chapterFacts([60, 62, 58, 61, 9], DAYS, [4, 4], {
            interval: 'day',
            lastPointInProgress: true,
            formatValue: String,
        })

        expect(facts).not.toContain('below')
        expect(facts).toContain('not over yet')
    })

    it('puts a chart marker straight above a peak', () => {
        const peak = [
            { x: 100, y: 200 },
            { x: 120, y: 50 },
            { x: 140, y: 200 },
        ]

        const [center] = placeMarkers([{ x: 120, y: 50 }], { lines: [peak], bars: [] }, MARKER_LAYOUT)

        expect(center?.x).toBeCloseTo(120)
        expect(center?.y).toBeCloseTo(28)
    })

    it.each([
        {
            name: 'a line that falls into the last point at the right edge',
            line: [
                { x: 320, y: 120 },
                { x: 360, y: 160 },
                { x: 400, y: 200 },
            ],
            anchors: [{ x: 400, y: 200 }],
        },
        {
            name: 'a spike that reaches the top of the chart',
            line: [
                { x: 100, y: 200 },
                { x: 120, y: 8 },
                { x: 140, y: 200 },
            ],
            anchors: [{ x: 120, y: 8 }],
        },
        {
            name: 'two marked points next to each other',
            line: [
                { x: 80, y: 150 },
                { x: 160, y: 150 },
            ],
            anchors: [
                { x: 110, y: 150 },
                { x: 120, y: 150 },
            ],
        },
    ])('keeps chart markers off the line, apart and inside the chart for $name', ({ line, anchors }) => {
        const centers = placeMarkers(anchors, { lines: [line], bars: [] }, MARKER_LAYOUT)
        const { radius, bounds } = MARKER_LAYOUT

        for (const [index, center] of centers.entries()) {
            expect(center.x - radius).toBeGreaterThanOrEqual(bounds.left)
            expect(center.x + radius).toBeLessThanOrEqual(bounds.right)
            expect(center.y - radius).toBeGreaterThanOrEqual(bounds.top)
            expect(center.y + radius).toBeLessThanOrEqual(bounds.bottom)
            for (const [from, to] of line.slice(1).map((point, i) => [line[i]!, point] as const)) {
                for (let t = 0; t <= 1; t += 0.02) {
                    const onLine = { x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t }
                    expect(Math.hypot(center.x - onLine.x, center.y - onLine.y)).toBeGreaterThanOrEqual(radius)
                }
            }
            for (const other of centers.slice(index + 1)) {
                expect(Math.hypot(center.x - other.x, center.y - other.y)).toBeGreaterThanOrEqual(radius * 2)
            }
        }
    })
    it.each<[string, string[], string, boolean]>([
        ['a marked name in another case', ['Germany'], 'Sign-ups from **germany** rose.', true],
        ['a name written out without marks', ['United Kingdom'], 'United States and United Kingdom held steady.', true],
        [
            'one value of a multi-breakdown series',
            ['Germany::Chrome', 'Germany', 'Chrome'],
            'Most of it came from Chrome.',
            true,
        ],
        ['a referrer with a symbol', ['$direct'], '$direct went from 80 to 160.', true],
        ['a marked name with a number, in another case', ['Windows 11'], 'Sign-ups from **windows 11** rose.', true],
        [
            'a marked value that holds a dash',
            ['signup - US - East', 'US - East'],
            'Most of it came from **us - east**.',
            true,
        ],
        [
            'another value that ends the same way',
            ['signup - US - East', 'US - East'],
            'It came from **Europe - East**.',
            false,
        ],
        ['a short value inside an ordinary word', ['US'], 'Let us look at the step up.', false],
        ['a short value inside an identifier', ['US'], 'US_East increased.', false],
        ['a value in another case that is not marked', ['Other'], 'Every other country stayed flat.', false],
        ['a value inside a longer name', ['India'], 'Indiana stayed flat.', false],
    ])('matches a series to the evidence that names it, for %s', (_, names, text, expected) => {
        expect(isSeriesNamedIn(names, text)).toBe(expected)
    })

    it('compares a stretch of a sparse chart by its non-zero points, as it does the rest of the chart', () => {
        const days = Array.from({ length: 8 }, (_, index) => `2026-10-0${index + 1}`)

        const facts = chapterFacts([0, 0, 100, 100, 0, 0, 100, 100], days, [0, 3], {
            interval: 'day',
            lastPointInProgress: false,
            formatValue: String,
        })

        expect(facts).toContain('in line with')
    })

    it('keeps the marker off an unfinished last point when the chapter has complete ones', () => {
        const anchor = anchorOf([100, 100, 100, 100, 150, 150, 150, 1], [4, 7], {
            interval: 'day',
            lastPointInProgress: true,
            formatValue: String,
        })

        expect(anchor).toBe(4)
    })

    it.each([
        ['quarter', '2026-04-01', 'Q2 2026'],
        ['year', '2024-01-01', '2024'],
    ])('names a %s by its period, with the year', (interval, day, expected) => {
        expect(dateLabel(day, interval)).toBe(expected)
    })
})
