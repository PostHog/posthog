import { CUSTOM_GROUP, FacetConfig, entryToFacetConfig, filterFacetsByName } from './facets'

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

    describe('entryToFacetConfig', () => {
        it('maps a resource entry to a removable Custom facet', () => {
            expect(entryToFacetConfig({ key: 'cloud.provider', attribute_type: 'resource' })).toMatchObject({
                group: CUSTOM_GROUP,
                title: 'cloud.provider',
                kind: 'dynamic',
                removable: true,
                searchable: true,
                source: { type: 'resourceAttribute', key: 'cloud.provider' },
            })
        })

        it('returns null for a log entry (needs the facet_attribute backend path)', () => {
            expect(entryToFacetConfig({ key: 'http.method', attribute_type: 'log' })).toBeNull()
        })
    })
})
