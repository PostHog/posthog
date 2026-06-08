import {
    buildFunnelBarHorizontalFiller,
    buildFunnelConversionStep,
    FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
    FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX,
} from './funnelBarHorizontalShared'

describe('funnelBarHorizontalShared', () => {
    describe('buildFunnelBarHorizontalFiller', () => {
        it('fills the bar up to 100% of the value domain', () => {
            const filler = buildFunnelBarHorizontalFiller(
                [
                    {
                        key: `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}0`,
                        label: 'a',
                        data: [30],
                        meta: { isDropOff: false, breakdownIndex: null },
                    },
                ],
                '#ccc'
            )
            expect(filler.key).toBe(FUNNEL_BAR_HORIZONTAL_FILLER_KEY)
            expect(filler.data).toEqual([70])
            expect(filler.meta).toEqual({ isDropOff: true, breakdownIndex: null })
            expect(filler.visibility).toEqual({ tooltip: false })
        })

        it('clamps to 0 when segments already exceed 100', () => {
            const filler = buildFunnelBarHorizontalFiller(
                [
                    {
                        key: `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}0`,
                        label: 'a',
                        data: [120],
                        meta: { isDropOff: false, breakdownIndex: null },
                    },
                ],
                '#ccc'
            )
            expect(filler.data).toEqual([0])
        })
    })

    describe('buildFunnelConversionStep', () => {
        it('builds a single converted segment plus a drop-off filler that sum to 100', () => {
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
            expect(segment.data).toEqual([42])
            expect(segment.color).toBe('#1d4aff')
            expect(segment.meta).toEqual({ isDropOff: false, breakdownIndex: null })

            expect(filler.key).toBe(FUNNEL_BAR_HORIZONTAL_FILLER_KEY)
            expect(filler.data).toEqual([58])
        })

        it('renders a full bar with no drop-off for the basis step', () => {
            const stepData = buildFunnelConversionStep({
                stepIndex: 0,
                label: 'Pageview',
                fractionOfBasis: 1,
                color: '#1d4aff',
                fillerColor: '#eee',
            })
            expect(stepData.series[0].data).toEqual([100])
            expect(stepData.series[1].data).toEqual([0])
        })
    })
})
