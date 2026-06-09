import {
    buildFunnelBarHorizontalFiller,
    buildFunnelConversionStep,
    FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
    FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX,
    funnelConversionRate,
} from './funnelBarHorizontalShared'

const segment = (value: number): Parameters<typeof buildFunnelBarHorizontalFiller>[0][number] => ({
    key: `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}0`,
    label: 'a',
    data: [value],
    meta: { isDropOff: false, breakdownIndex: null },
})

describe('funnelBarHorizontalShared', () => {
    describe('funnelConversionRate', () => {
        it.each([
            { count: 50, basisCount: 100, expected: 0.5, description: 'partial conversion' },
            { count: 100, basisCount: 100, expected: 1, description: 'full conversion' },
            { count: 0, basisCount: 100, expected: 0, description: 'zero count' },
            { count: 5, basisCount: 0, expected: 0, description: 'zero basis guards divide-by-zero' },
        ])('$description', ({ count, basisCount, expected }) => {
            expect(funnelConversionRate(count, basisCount)).toBe(expected)
        })
    })

    describe('buildFunnelBarHorizontalFiller', () => {
        it.each([
            { segmentValues: [30], expectedFiller: 70, description: 'fills the remaining percentage up to 100' },
            { segmentValues: [30, 50], expectedFiller: 20, description: 'sums multiple segments before filling' },
            { segmentValues: [120], expectedFiller: 0, description: 'clamps to 0 when segments exceed 100' },
        ])('$description', ({ segmentValues, expectedFiller }) => {
            const filler = buildFunnelBarHorizontalFiller(segmentValues.map(segment), '#ccc')
            expect(filler.key).toBe(FUNNEL_BAR_HORIZONTAL_FILLER_KEY)
            expect(filler.data).toEqual([expectedFiller])
            expect(filler.meta).toEqual({ isDropOff: true, breakdownIndex: null })
            expect(filler.visibility).toEqual({ tooltip: false })
        })
    })

    describe('buildFunnelConversionStep', () => {
        it('builds a converted segment carrying the label, color, and meta', () => {
            const stepData = buildFunnelConversionStep({
                stepIndex: 1,
                label: 'Signed up',
                fractionOfBasis: 0.42,
                color: '#1d4aff',
                fillerColor: '#eee',
            })
            expect(stepData.label).toBe('1')
            expect(stepData.series).toHaveLength(2)

            const [segment, filler] = stepData.series
            expect(segment.label).toBe('Signed up')
            expect(segment.color).toBe('#1d4aff')
            expect(segment.meta).toEqual({ isDropOff: false, breakdownIndex: null })
            expect(filler.key).toBe(FUNNEL_BAR_HORIZONTAL_FILLER_KEY)
        })

        it.each([
            { fractionOfBasis: 0, expectedSegment: 0, expectedFiller: 100, description: 'fully dropped step' },
            { fractionOfBasis: 0.42, expectedSegment: 42, expectedFiller: 58, description: 'partial conversion' },
            { fractionOfBasis: 1, expectedSegment: 100, expectedFiller: 0, description: 'full basis step' },
        ])('$description: segment + filler sum to 100', ({ fractionOfBasis, expectedSegment, expectedFiller }) => {
            const stepData = buildFunnelConversionStep({
                stepIndex: 0,
                label: 'Pageview',
                fractionOfBasis,
                color: '#1d4aff',
                fillerColor: '#eee',
            })
            expect(stepData.series[0].data).toEqual([expectedSegment])
            expect(stepData.series[1].data).toEqual([expectedFiller])
        })
    })
})
