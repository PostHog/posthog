import type { AEOBrandApi, AEOBrandDetailApi, AEOBrandRatesApi } from '../generated/api.schemas'
import { brandDetailKpis, brandPickerGroups } from './brandDetail'

const rates = (overrides: Partial<AEOBrandRatesApi>): AEOBrandRatesApi => ({
    answers: 200,
    answers_mentioning: 80,
    visibility: 0.4,
    citation_rate: 0.2,
    average_position: 2.4,
    positive_share: 0.6,
    ...overrides,
})

const brand = (
    id: string,
    kind: AEOBrandApi['kind'],
    name: string,
    status: AEOBrandApi['status'] = 'confirmed'
): AEOBrandApi => ({
    id,
    name,
    domain: `${name.toLowerCase()}.example.com`,
    kind,
    status,
    source: 'manual',
    aliases: [],
    created_at: '2026-10-01T00:00:00Z',
    updated_at: null,
})

const detailOf = (overrides: Partial<AEOBrandDetailApi>): AEOBrandDetailApi => ({
    brand: brand('acme', 'competitor', 'Acme'),
    domains: ['acme.example.com'],
    window_from: '2026-10-01',
    window_to: '2026-10-30',
    days: 30,
    branded: 'non_branded',
    engine: null,
    topic: null,
    current: rates({}),
    previous: rates({ visibility: 0.3546, average_position: 3.0 }),
    latest_date: '2026-10-29',
    latest: rates({ visibility: 0.5 }),
    days_with_answers: 29,
    prompts: [],
    cited_sites: [],
    sentiment: { scored: 0, positive_share: null, neutral_share: null, negative_share: null, examples: [] },
    searches: [],
    ...overrides,
})

describe('brandDetail', () => {
    it('compares each figure with the range before as it is shown, and a lower position counts as better', () => {
        const kpis = Object.fromEntries(brandDetailKpis(detailOf({})).map((kpi) => [kpi.key, kpi]))

        expect(kpis.visibility).toMatchObject({
            formatted: '40%',
            subtitle: 'vs. 35% prior',
            change: 5,
            changeLabel: '+5 pts',
            goodDirection: 'up',
            latest: 'Oct 29: 50%',
            delta: { label: '+5 pts', direction: 'up', tooltip: 'Against the 30 days before, in percentage points' },
        })
        expect(kpis.average_position).toMatchObject({
            formatted: '#2.4',
            change: -0.6,
            changeLabel: '-0.6',
            goodDirection: 'down',
            delta: { label: '0.6 better', direction: 'up', tooltip: 'Against the 30 days before. Lower is better' },
        })
    })

    it('leaves out the comparison when the range before has too few answers, and the figure when it has no base', () => {
        const kpis = brandDetailKpis(
            detailOf({ previous: null, current: rates({ average_position: null }), latest: null, latest_date: null })
        )

        expect(kpis.map(({ key, subtitle, change, latest }) => [key, subtitle, change, latest])).toEqual([
            ['visibility', null, null, null],
            ['citation_rate', null, null, null],
            ['average_position', null, null, null],
            ['positive_share', null, null, null],
        ])
        expect(kpis.find((kpi) => kpi.key === 'average_position')).toMatchObject({ value: null, formatted: null })
    })

    it('offers one own brand, the open one when it is own, and leaves out ignored brands but the open one', () => {
        const brands = [
            brand('own-b', 'own', 'Beta'),
            brand('own-a', 'own', 'Alpha'),
            brand('rival', 'competitor', 'Rival'),
            brand('gone', 'competitor', 'Gone', 'ignored'),
            brand('review', 'publisher', 'Reviews'),
        ]

        expect(
            brandPickerGroups(brands, brands[0]).map(({ label, options }) => [
                label,
                options.map((option) => option.id),
            ])
        ).toEqual([
            ['Your brand', ['own-b']],
            ['Competitors', ['rival']],
            ['Publishers', ['review']],
        ])
        expect(brandPickerGroups(brands, brands[3])[1].options.map((option) => option.id)).toEqual(['gone', 'rival'])
        expect(brandPickerGroups(brands, null)[0].options.map((option) => option.id)).toEqual(['own-a'])
    })
})
