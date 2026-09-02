import { PathsV2Results } from '~/queries/schema/schema-general'

import {
    OTHER_ROW_KEY,
    buildJourneyGridModel,
    chainCardKey,
    dominantDisplayedChain,
    isChainDisplayed,
    journeyItemKey,
    journeyItemLabel,
} from './journeyGridModel'

const item = (event: string, label?: string | null): { event: string; label?: string | null } => ({ event, label })

describe('journeyGridModel', () => {
    describe('buildJourneyGridModel', () => {
        it('returns an empty model for null or empty results', () => {
            expect(buildJourneyGridModel(null)).toEqual({
                columns: [],
                ribbons: [],
                maxRibbonCount: 0,
                displayedItemKeys: new Set(),
            })
            expect(buildJourneyGridModel({ steps: [], edges: [], prefixes: [] })).toEqual({
                columns: [],
                ribbons: [],
                maxRibbonCount: 0,
                displayedItemKeys: new Set(),
            })
        })

        it('orders each column as named rows, then other, then drop-off, with per-step totals', () => {
            const results: PathsV2Results = {
                steps: [
                    {
                        stepIndex: 0,
                        rows: [
                            { item: item('$pageview', '/home'), count: 60 },
                            { item: item('$pageview', '/pricing'), count: 30 },
                        ],
                        otherCount: 10,
                        dropOffCount: 25,
                    },
                ],
                edges: [],
                prefixes: [],
            }

            const model = buildJourneyGridModel(results)

            expect(model.columns).toHaveLength(1)
            const column = model.columns[0]
            // The displayed total is named rows plus the other row; drop-off actors are already in those rows
            expect(column.total).toEqual(100)
            expect(column.rows.map((row) => [row.kind, row.label, row.count, row.fraction])).toEqual([
                ['item', '/home', 60, 0.6],
                ['item', '/pricing', 30, 0.3],
                ['other', 'Other', 10, 0.1],
                ['dropOff', 'Ends here', 25, 0.25],
            ])
        })

        it('omits zero-count other and drop-off rows and survives an all-zero column', () => {
            const model = buildJourneyGridModel({
                steps: [{ stepIndex: 0, rows: [], otherCount: 0, dropOffCount: 0 }],
                edges: [],
                prefixes: [],
            })
            expect(model.columns[0].rows).toEqual([])
            expect(model.columns[0].total).toEqual(0)
        })

        it('sorts columns by step index', () => {
            const model = buildJourneyGridModel({
                steps: [
                    { stepIndex: 1, rows: [{ item: item('a', null), count: 1 }], otherCount: 0, dropOffCount: 0 },
                    { stepIndex: 0, rows: [{ item: item('b', null), count: 2 }], otherCount: 0, dropOffCount: 0 },
                ],
                edges: [],
                prefixes: [],
            })
            expect(model.columns.map((column) => column.stepIndex)).toEqual([0, 1])
        })

        it('resolves ribbons to rows, mapping null endpoints to the other row', () => {
            const results: PathsV2Results = {
                steps: [
                    {
                        stepIndex: 0,
                        rows: [{ item: item('$pageview', '/home'), count: 50 }],
                        otherCount: 5,
                        dropOffCount: 0,
                    },
                    {
                        stepIndex: 1,
                        rows: [{ item: item('$pageview', '/pricing'), count: 20 }],
                        otherCount: 8,
                        dropOffCount: 0,
                    },
                ],
                edges: [
                    {
                        stepIndex: 0,
                        source: item('$pageview', '/home'),
                        target: item('$pageview', '/pricing'),
                        count: 20,
                    },
                    { stepIndex: 0, source: item('$pageview', '/home'), target: null, count: 5 },
                    { stepIndex: 0, source: null, target: item('$pageview', '/pricing'), count: 3 },
                ],
                prefixes: [],
            }

            const model = buildJourneyGridModel(results)

            expect(model.ribbons.map((ribbon) => [ribbon.sourceKey, ribbon.targetKey, ribbon.count])).toEqual([
                [journeyItemKey(item('$pageview', '/home')), journeyItemKey(item('$pageview', '/pricing')), 20],
                [journeyItemKey(item('$pageview', '/home')), OTHER_ROW_KEY, 5],
                [OTHER_ROW_KEY, journeyItemKey(item('$pageview', '/pricing')), 3],
            ])
            // Edge share is relative to the source row's count (positional: ribbons subset their cards)
            expect(model.ribbons[0].fractionOfSource).toEqual(0.4)
            expect(model.ribbons[2].fractionOfSource).toEqual(0.6)
            expect(model.maxRibbonCount).toEqual(20)
        })

        it('skips zero-count edges and edges whose endpoints are not in the grid', () => {
            const model = buildJourneyGridModel({
                steps: [
                    {
                        stepIndex: 0,
                        rows: [{ item: item('$pageview', '/home'), count: 10 }],
                        otherCount: 0,
                        dropOffCount: 0,
                    },
                    {
                        stepIndex: 1,
                        rows: [{ item: item('$pageview', '/pricing'), count: 10 }],
                        otherCount: 0,
                        dropOffCount: 0,
                    },
                ],
                edges: [
                    { stepIndex: 0, source: item('$pageview', '/home'), target: item('$pageview', '/gone'), count: 4 },
                    { stepIndex: 0, source: null, target: item('$pageview', '/pricing'), count: 2 },
                    {
                        stepIndex: 0,
                        source: item('$pageview', '/home'),
                        target: item('$pageview', '/pricing'),
                        count: 0,
                    },
                ],
                prefixes: [],
            })
            expect(model.ribbons).toEqual([])
        })

        it('lists only the named rows it renders as displayed item keys', () => {
            const model = buildJourneyGridModel({
                steps: [
                    {
                        stepIndex: 0,
                        rows: [{ item: item('$pageview', '/home'), count: 10 }],
                        otherCount: 3,
                        dropOffCount: 2,
                    },
                ],
                edges: [],
                prefixes: [],
            })
            expect(model.displayedItemKeys).toEqual(new Set([chainCardKey(0, item('$pageview', '/home'))]))
        })
    })

    describe('hover chain selection', () => {
        const home = item('$pageview', '/home')
        const cart = item('$pageview', '/cart')
        const hidden = item('$pageview', '/hidden')
        const checkout = item('$pageview', '/checkout')
        const displayed = new Set([chainCardKey(0, home), chainCardKey(1, cart), chainCardKey(2, checkout)])

        it('picks the dominant chain ending at the card, prefixes arriving count-descending', () => {
            const prefixes = [
                { items: [home, cart, checkout], count: 30 },
                { items: [home, cart], count: 40 },
                { items: [home], count: 100 },
            ]
            expect(dominantDisplayedChain(prefixes, 2, journeyItemKey(checkout), displayed)).toEqual([
                home,
                cart,
                checkout,
            ])
        })

        it('skips chains running through an item the grid bucketed into the other row', () => {
            // The dominant chain reaches /checkout via /hidden, which has no card, so previewing it
            // would break the highlight and name an item the chart never showed.
            const prefixes = [
                { items: [home, hidden, checkout], count: 90 },
                { items: [home, cart, checkout], count: 10 },
            ]
            expect(dominantDisplayedChain(prefixes, 2, journeyItemKey(checkout), displayed)).toEqual([
                home,
                cart,
                checkout,
            ])
        })

        it('returns null when no chain of the right length and ending is displayable', () => {
            const prefixes = [{ items: [home, hidden, checkout], count: 90 }]
            expect(dominantDisplayedChain(prefixes, 2, journeyItemKey(checkout), displayed)).toBeNull()
            // A chain of the wrong length never matches a card at that column
            expect(
                dominantDisplayedChain([{ items: [home, cart], count: 5 }], 2, journeyItemKey(cart), displayed)
            ).toBeNull()
        })

        it('treats a chain as displayed only when every position has a card', () => {
            expect(isChainDisplayed([home, cart], displayed)).toBe(true)
            expect(isChainDisplayed([home, hidden], displayed)).toBe(false)
            // Right items, wrong positions
            expect(isChainDisplayed([cart, home], displayed)).toBe(false)
        })
    })

    describe('item identity and labels', () => {
        it('keeps a null label (no naming property) distinct from an empty label', () => {
            expect(journeyItemKey(item('$pageview', null))).not.toEqual(journeyItemKey(item('$pageview', '')))
        })

        test.each([
            ['a null label falls back to the event name', item('custom_event', null), 'custom_event'],
            ['an undefined label falls back to the event name', item('custom_event'), 'custom_event'],
            ['an empty label reads as empty', item('$pageview', ''), '(empty)'],
            ['a set label is used as is', item('$pageview', '/home'), '/home'],
        ])('%s', (_name, input, expected) => {
            expect(journeyItemLabel(input)).toEqual(expected)
        })
    })
})
