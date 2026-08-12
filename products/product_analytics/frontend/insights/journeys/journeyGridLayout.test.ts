import { PathsV2Results } from '~/queries/schema/schema-general'

import {
    BAR_HEIGHT_BUDGET,
    LABEL_BLOCK_HEIGHT,
    MIN_BAR_HEIGHT,
    MIN_RIBBON_THICKNESS,
    buildJourneyGridLayout,
} from './journeyGridLayout'
import { buildJourneyGridModel } from './journeyGridModel'

const item = (event: string): { event: string } => ({ event })

const results: PathsV2Results = {
    steps: [
        { stepIndex: 0, rows: [{ item: item('a'), count: 1000 }], otherCount: 0, dropOffCount: 200 },
        {
            stepIndex: 1,
            rows: [
                { item: item('b'), count: 500 },
                { item: item('c'), count: 250 },
                { item: item('d'), count: 1 },
            ],
            otherCount: 49,
            dropOffCount: 800,
        },
    ],
    edges: [
        { stepIndex: 0, source: item('a'), target: item('b'), count: 500 },
        { stepIndex: 0, source: item('a'), target: item('c'), count: 250 },
        { stepIndex: 0, source: item('a'), target: item('d'), count: 1 },
        { stepIndex: 0, source: item('a'), target: null, count: 49 },
    ],
    prefixes: [],
}

describe('buildJourneyGridLayout', () => {
    it('sizes bars from one shared px-per-actor scale, with the largest column filling the budget', () => {
        const layout = buildJourneyGridLayout(buildJourneyGridModel(results))

        const barOf = (stepIndex: number, event: string): number =>
            layout.rows.find((r) => r.stepIndex === stepIndex && r.row.label === event)!.barHeight

        expect(barOf(0, 'a')).toBeCloseTo(BAR_HEIGHT_BUDGET)
        // Cross-column comparability: half the actors means half the bar height, on the same scale
        expect(barOf(1, 'b')).toBeCloseTo(BAR_HEIGHT_BUDGET / 2)
        expect(barOf(1, 'c')).toBeCloseTo(BAR_HEIGHT_BUDGET / 4)
    })

    it('clamps tiny counts to visible minimum bar and ribbon sizes', () => {
        const layout = buildJourneyGridLayout(buildJourneyGridModel(results))

        const tinyRow = layout.rows.find((r) => r.row.label === 'd')!
        expect(tinyRow.barHeight).toEqual(MIN_BAR_HEIGHT)
        const tinyRibbon = layout.ribbons.find((r) => r.ribbon.targetKey === tinyRow.row.key)!
        expect(tinyRibbon.toThickness).toBeGreaterThanOrEqual(MIN_RIBBON_THICKNESS)
    })

    it('tiles each bar edge contiguously without spilling past the bar bottom', () => {
        const layout = buildJourneyGridLayout(buildJourneyGridModel(results))

        const source = layout.rows.find((r) => r.stepIndex === 0 && r.row.label === 'a')!
        const outbound = layout.ribbons.filter((r) => r.ribbon.sourceStep === 0).sort((a, b) => a.fromY - b.fromY)
        expect(outbound[0].fromY).toEqual(source.barY)
        let cursor = source.barY
        for (const band of outbound) {
            expect(band.fromY).toBeCloseTo(cursor)
            cursor += band.fromThickness
        }
        expect(cursor).toBeLessThanOrEqual(source.barY + source.barHeight + 1e-6)
    })

    it('squeezes inflated bands to fit when minimum thicknesses overflow a tiny bar', () => {
        const sources = ['a', 'b', 'c', 'd', 'e']
        const manyIntoTiny: PathsV2Results = {
            steps: [
                {
                    stepIndex: 0,
                    rows: sources.map((event) => ({ item: item(event), count: 300 })),
                    otherCount: 0,
                    dropOffCount: 0,
                },
                { stepIndex: 1, rows: [{ item: item('z'), count: 5 }], otherCount: 1495, dropOffCount: 0 },
            ],
            edges: sources.flatMap((event) => [
                { stepIndex: 0, source: item(event), target: item('z'), count: 1 },
                { stepIndex: 0, source: item(event), target: null, count: 299 },
            ]),
            prefixes: [],
        }
        const layout = buildJourneyGridLayout(buildJourneyGridModel(manyIntoTiny))

        const target = layout.rows.find((r) => r.stepIndex === 1 && r.row.label === 'z')!
        const inbound = layout.ribbons.filter((r) => r.ribbon.targetKey === target.row.key)
        const totalIn = inbound.reduce((sum, band) => sum + band.toThickness, 0)
        expect(target.barHeight).toEqual(MIN_BAR_HEIGHT)
        expect(totalIn).toBeLessThanOrEqual(target.barHeight + 1e-6)
    })

    it('renders drop-off rows as text-only blocks with no bar and no ribbon endpoints', () => {
        const layout = buildJourneyGridLayout(buildJourneyGridModel(results))

        const dropOffs = layout.rows.filter((r) => r.row.kind === 'dropOff')
        expect(dropOffs).toHaveLength(2)
        expect(dropOffs.every((r) => r.barHeight === 0)).toBe(true)
        // A drop-off row sits below the previous row's bar, offset by the label block, never overlapping
        const source = layout.rows.find((r) => r.stepIndex === 0 && r.row.label === 'a')!
        expect(dropOffs[0].labelY).toBeGreaterThanOrEqual(source.labelY + LABEL_BLOCK_HEIGHT + source.barHeight)
    })
})
