import type { TrendsQuery } from '~/queries/schema/schema-general'

import { chapterCause, isUnclear } from './chartCauses'
import type { ModelCause } from './chartCauses'
import { findChartMoments } from './chartMoments'
import type { ChartMoment } from './chartMoments'
import { buildEvidenceQueries, evidenceForMoment } from './momentEvidence'
import type { MomentEvidence } from './momentEvidence'

const days = (count: number): string[] =>
    Array.from({ length: count }, (_, index) => new Date(Date.UTC(2026, 8, 1 + index)).toISOString().slice(0, 10))

const steady = (count: number, level: number): number[] =>
    Array.from({ length: count }, (_, index) => level + (index % 3) - 1)

const SPIKE = steady(30, 60).map((value, index) => (index === 14 ? 498 : value))

const PEAK: ChartMoment = { id: 'peak-14', kind: 'peak', range: [14, 14], direction: 'up', title: 'A peak' }
const finding = (overrides: Partial<MomentEvidence>): MomentEvidence => ({
    text: '',
    query: null,
    driverShare: null,
    driver: null,
    cause: null,
    ...overrides,
})
const PAGE = finding({ driverShare: 0.9, driver: { key: '$pathname', value: '/pricing' } })
const REFERRER = finding({ driverShare: 0.7, driver: { key: '$referring_domain', value: 'news.example.com' } })
const ONE_PERSON = finding({ driverShare: 1, cause: 'one_person' })
const STEP = [...steady(15, 20), ...steady(15, 60)]

describe('explain chart moments', () => {
    test.each([
        ['a one-day spike is a peak', SPIKE, ['peak'], [[14, 14]]],
        ['a lasting change of level is a shift, not a peak', STEP, ['shift'], [[15, 29]]],
        ['a steady chart has nothing to explain', steady(30, 50), [], []],
    ])('%s', (_, data, kinds, ranges) => {
        const moments = findChartMoments({ data, days: days(data.length) }, { interval: 'day', incompletePoints: 0 })

        expect(moments.map((moment) => moment.kind)).toEqual(kinds)
        expect(moments.map((moment) => moment.range)).toEqual(ranges)
    })

    test.each([
        ['an outside referrer', 'www.example.com', 'came from the referrer ⟦n:news.example.com⟧'],
        ['the site itself', 'news.example.com', 'came from people already on ⟦n:news.example.com⟧'],
    ])('names a referrer that carries a peak: %s', (_, host, phrase) => {
        const [peak] = findChartMoments({ data: SPIKE, days: days(30) }, { interval: 'day', incompletePoints: 0 })
        const query = { kind: 'TrendsQuery', series: [] } as unknown as TrendsQuery
        const rows = [
            { breakdown_value: 'news.example.com', data: SPIKE.map((_, index) => (index === 14 ? 420 : 2)) },
            { breakdown_value: '$direct', data: SPIKE.map((value, index) => (index === 14 ? 78 : value - 2)) },
        ]
        const hostRows = [{ breakdown_value: host, data: SPIKE }]

        const evidence = evidenceForMoment(
            peak,
            {
                breakdowns: [
                    { property: { key: '$referring_domain', noun: 'referrer' }, query, rows },
                    { property: { key: '$host', noun: 'host' }, query, rows: hostRows },
                ],
                people: null,
            },
            { values: SPIKE, completePoints: SPIKE.length, interval: 'day', formatValue: String }
        )

        expect(evidence).toEqual([
            expect.objectContaining({ text: expect.stringContaining(phrase), driverShare: expect.any(Number) }),
        ])
        expect(evidence[0].driverShare).toBeGreaterThan(0.8)
    })

    test.each<[string, MomentEvidence[], ModelCause | null, string, boolean]>([
        [
            'evidence of one person outranks the model',
            [ONE_PERSON, REFERRER],
            { cause: 'outside_traffic', confidence: 0.95 },
            'most likely one person',
            false,
        ],
        [
            'an unsure model answer is not shown',
            [PAGE],
            { cause: 'tracking', confidence: 0.3 },
            'most likely linked to ⟦n:/pricing⟧',
            false,
        ],
        [
            'outside traffic names the referrer, not the page',
            [PAGE, REFERRER],
            { cause: 'outside_traffic', confidence: 0.9 },
            'most likely more people arriving from ⟦n:news.example.com⟧',
            false,
        ],
        [
            'an unclear answer is not shown as a cause, and asks for a deeper look',
            [PAGE],
            { cause: 'unclear', confidence: 0.8 },
            'most likely linked to ⟦n:/pricing⟧',
            true,
        ],
    ])('the likely cause of a step: %s', (_, evidence, model, clause, unclear) => {
        const cause = chapterCause(PEAK, evidence, model)

        expect(cause?.clause).toContain(clause)
        expect(isUnclear(cause, model)).toBe(unclear)
    })

    test.each([
        ['total count', true, undefined],
        ['sum', true, 'sum'],
        ['unique users', false, 'dau'],
        ['average', false, 'avg'],
    ])('a %s chart is split to find a cause: %s', (_, splits, math) => {
        const source = {
            kind: 'TrendsQuery',
            series: [{ kind: 'EventsNode', event: 'signed_up', math, math_property: math ? 'amount' : undefined }],
        } as unknown as TrendsQuery

        expect(!!buildEvidenceQueries(source, 0)).toBe(splits)
    })
})
