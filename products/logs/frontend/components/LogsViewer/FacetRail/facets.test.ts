import { FacetOption } from './Facet'
import { FacetConfig, filterFacetsByName, mergeSelectedIntoOptions } from './facets'

const facet = (key: string, title: string, group: string): FacetConfig => ({
    key,
    title,
    group,
    kind: 'dynamic',
    source: { type: 'resourceAttribute', key },
})

const FACETS: FacetConfig[] = [
    facet('level', 'Level', 'Standard'),
    facet('service', 'Service', 'Standard'),
    facet('namespace', 'Namespace', 'Kubernetes'),
    facet('pod', 'Pod', 'Kubernetes'),
    facet('host', 'Host', 'Infrastructure'),
]

describe('facets', () => {
    describe('filterFacetsByName', () => {
        it.each([
            ['blank query returns all', '', ['level', 'service', 'namespace', 'pod', 'host']],
            ['whitespace-only returns all', '   ', ['level', 'service', 'namespace', 'pod', 'host']],
            ['matches a field title', 'namespace', ['namespace']],
            ['title match is case-insensitive', 'NAMESPACE', ['namespace']],
            ['partial title match', 'serv', ['service']],
            ['matches a whole group by name', 'kubernetes', ['namespace', 'pod']],
            ['group match is case-insensitive', 'INFRA', ['host']],
            ['no match returns empty', 'zzz', []],
        ])('%s', (_, query, expectedKeys) => {
            expect(filterFacetsByName(FACETS, query).map((f) => f.key)).toEqual(expectedKeys)
        })
    })

    describe('mergeSelectedIntoOptions', () => {
        const fetched: FacetOption[] = [
            { value: 'api', label: 'api', count: 10 },
            { value: 'worker', label: 'worker', count: 5 },
        ]

        it.each<[string, string[], string | undefined, string[]]>([
            ['no selected values leaves fetched unchanged', [], undefined, ['api', 'worker']],
            ['selected value already fetched is not duplicated', ['api'], undefined, ['api', 'worker']],
            ['missing selected value is prepended', ['batch-exports'], undefined, ['batch-exports', 'api', 'worker']],
            ['multiple missing values keep selection order', ['b', 'a'], undefined, ['b', 'a', 'api', 'worker']],
            ['missing selected value not matching the search is omitted', ['batch-exports'], 'api', ['api', 'worker']],
            [
                'search match is a case-insensitive substring',
                ['Batch-Exports'],
                'batch',
                ['Batch-Exports', 'api', 'worker'],
            ],
        ])('%s', (_, selected, search, expectedValues) => {
            expect(mergeSelectedIntoOptions(fetched, selected, search).map((o) => o.value)).toEqual(expectedValues)
        })

        it('injects missing selected values with a zero count', () => {
            expect(mergeSelectedIntoOptions(fetched, ['batch-exports'], undefined)[0]).toEqual({
                value: 'batch-exports',
                label: 'batch-exports',
                count: 0,
            })
        })
    })
})
