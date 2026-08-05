import { PathsV2Results } from '~/queries/schema/schema-general'

import {
    CARD_HEIGHT,
    JourneyGridGeometry,
    MIN_RIBBON_THICKNESS,
    PORT_TOP_OFFSET,
    cardKey,
    computeJourneyGridGeometry,
} from './journeyGridGeometry'
import { buildJourneyGridModel } from './journeyGridModel'

const item = (event: string, label: string): { event: string; label: string } => ({ event, label })

/** Every ribbon end must sit inside its card's port area — a spilled stack detaches ribbons
 * from their cards visually. */
function expectPortsWithinCards(geometry: JourneyGridGeometry): void {
    const cardByKey = new Map(geometry.cards.map((card) => [cardKey(card.stepIndex, card.row.key), card]))
    for (const { ribbon, sourceThickness, targetThickness, fromY, toY } of geometry.ribbons) {
        const source = cardByKey.get(cardKey(ribbon.sourceStep, ribbon.sourceKey))!
        const target = cardByKey.get(cardKey(ribbon.sourceStep + 1, ribbon.targetKey))!
        expect(fromY).toBeGreaterThanOrEqual(source.y + PORT_TOP_OFFSET)
        expect(fromY + sourceThickness).toBeLessThanOrEqual(source.y + CARD_HEIGHT - PORT_TOP_OFFSET)
        expect(toY).toBeGreaterThanOrEqual(target.y + PORT_TOP_OFFSET)
        expect(toY + targetThickness).toBeLessThanOrEqual(target.y + CARD_HEIGHT - PORT_TOP_OFFSET)
    }
}

describe('journeyGridGeometry', () => {
    it('renders uniform tiny counts as minimum-thickness ribbons that stay attached to their card', () => {
        // A big population ending at step 1 plus a handful of count-1 continuations: normalizing
        // against the largest edge count would render every ribbon at maximum thickness and spill
        // the out-stack ~90px past the 66px card.
        const results: PathsV2Results = {
            steps: [
                {
                    stepIndex: 0,
                    rows: [
                        { item: item('$pageview', '/a'), count: 120 },
                        { item: item('$pageview', '/b'), count: 80 },
                        { item: item('$pageview', '/c'), count: 40 },
                    ],
                    otherCount: 5,
                    dropOffCount: 245,
                },
                {
                    stepIndex: 1,
                    rows: [
                        { item: item('$pageview', '/d'), count: 1 },
                        { item: item('$pageview', '/e'), count: 1 },
                        { item: item('$pageview', '/f'), count: 1 },
                    ],
                    otherCount: 1,
                    dropOffCount: 0,
                },
            ],
            edges: [
                { stepIndex: 0, source: null, target: item('$pageview', '/d'), count: 1 },
                { stepIndex: 0, source: null, target: item('$pageview', '/e'), count: 1 },
                { stepIndex: 0, source: null, target: item('$pageview', '/f'), count: 1 },
                { stepIndex: 0, source: null, target: null, count: 1 },
            ],
            prefixes: [],
        }

        const geometry = computeJourneyGridGeometry(buildJourneyGridModel(results))

        expect(geometry.ribbons).toHaveLength(4)
        for (const ribbon of geometry.ribbons) {
            expect(ribbon.sourceThickness).toEqual(MIN_RIBBON_THICKNESS)
            expect(ribbon.targetThickness).toEqual(MIN_RIBBON_THICKNESS)
        }
        expectPortsWithinCards(geometry)
    })

    it('squeezes an overflowing port stack to fit the card while keeping counts ordered by thickness', () => {
        // One dominant continuation plus a long tail of minimum-thickness ribbons out of a single
        // card: proportional thicknesses alone sum past the card height (counts are deduped per
        // element, so a side's counts are not bounded by the card's own count).
        const tailTargets = ['/t1', '/t2', '/t3', '/t4', '/t5', '/t6', '/t7']
        const results: PathsV2Results = {
            steps: [
                {
                    stepIndex: 0,
                    rows: [{ item: item('$pageview', '/start'), count: 100 }],
                    otherCount: 0,
                    dropOffCount: 0,
                },
                {
                    stepIndex: 1,
                    rows: [
                        { item: item('$pageview', '/main'), count: 95 },
                        ...tailTargets.map((label) => ({ item: item('$pageview', label), count: 1 })),
                    ],
                    otherCount: 2,
                    dropOffCount: 0,
                },
            ],
            edges: [
                { stepIndex: 0, source: item('$pageview', '/start'), target: item('$pageview', '/main'), count: 95 },
                ...tailTargets.map((label) => ({
                    stepIndex: 0,
                    source: item('$pageview', '/start'),
                    target: item('$pageview', label),
                    count: 1,
                })),
                { stepIndex: 0, source: item('$pageview', '/start'), target: null, count: 2 },
            ],
            prefixes: [],
        }

        const geometry = computeJourneyGridGeometry(buildJourneyGridModel(results))

        expect(geometry.ribbons).toHaveLength(9)
        expectPortsWithinCards(geometry)
        const dominant = geometry.ribbons.find(({ ribbon }) => ribbon.count === 95)!
        const tail = geometry.ribbons.filter(({ ribbon }) => ribbon.count === 1)
        for (const thin of tail) {
            expect(dominant.sourceThickness).toBeGreaterThan(thin.sourceThickness)
        }
    })

    it('keeps unclamped thickness proportional to count', () => {
        const results: PathsV2Results = {
            steps: [
                {
                    stepIndex: 0,
                    rows: [
                        { item: item('$pageview', '/a'), count: 10 },
                        { item: item('$pageview', '/b'), count: 10 },
                    ],
                    otherCount: 0,
                    dropOffCount: 0,
                },
                {
                    stepIndex: 1,
                    rows: [{ item: item('$pageview', '/c'), count: 15 }],
                    otherCount: 0,
                    dropOffCount: 0,
                },
            ],
            edges: [
                { stepIndex: 0, source: item('$pageview', '/a'), target: item('$pageview', '/c'), count: 10 },
                { stepIndex: 0, source: item('$pageview', '/b'), target: item('$pageview', '/c'), count: 5 },
            ],
            prefixes: [],
        }

        const geometry = computeJourneyGridGeometry(buildJourneyGridModel(results))

        const [big, small] = [...geometry.ribbons].sort((a, b) => b.ribbon.count - a.ribbon.count)
        expect(big.sourceThickness).toEqual(2 * small.sourceThickness)
        expect(small.sourceThickness).toBeGreaterThan(MIN_RIBBON_THICKNESS)
        expectPortsWithinCards(geometry)
    })
})
