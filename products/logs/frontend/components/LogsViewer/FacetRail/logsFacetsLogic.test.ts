import { RecentTaxonomicFilter } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { buildRecentFacets } from './logsFacetsLogic'

const recent = (
    groupType: TaxonomicFilterGroupType,
    value: string | number | null,
    timestamp = 0
): RecentTaxonomicFilter => ({
    groupType,
    groupName: 'group',
    value,
    item: {},
    timestamp,
})

describe('buildRecentFacets', () => {
    it('maps resource and log attribute recents onto their facet sources', () => {
        const facets = buildRecentFacets([
            recent(TaxonomicFilterGroupType.LogResourceAttributes, 'k8s.namespace.name'),
            recent(TaxonomicFilterGroupType.LogAttributes, 'http.status_code'),
        ])

        expect(facets).toHaveLength(2)
        expect(facets[0]).toMatchObject({
            title: 'k8s.namespace.name',
            group: 'Recent',
            kind: 'dynamic',
            source: { type: 'resourceAttribute', key: 'k8s.namespace.name' },
        })
        expect(facets[1].source).toEqual({ type: 'logAttribute', key: 'http.status_code' })
    })

    it('ignores group types that do not map onto a map facet', () => {
        const facets = buildRecentFacets([
            recent(TaxonomicFilterGroupType.Logs, 'message'),
            recent(TaxonomicFilterGroupType.Events, 'pageview'),
            recent(TaxonomicFilterGroupType.LogAttributes, 'http.method'),
        ])

        expect(facets.map((f) => f.source)).toEqual([{ type: 'logAttribute', key: 'http.method' }])
    })

    it('dedupes by source + key but keeps the same key across resource and log attributes', () => {
        const facets = buildRecentFacets([
            recent(TaxonomicFilterGroupType.LogAttributes, 'status', 3),
            recent(TaxonomicFilterGroupType.LogAttributes, 'status', 2),
            recent(TaxonomicFilterGroupType.LogResourceAttributes, 'status', 1),
        ])

        expect(facets.map((f) => f.source)).toEqual([
            { type: 'logAttribute', key: 'status' },
            { type: 'resourceAttribute', key: 'status' },
        ])
    })

    it('drops entries with an empty value', () => {
        expect(buildRecentFacets([recent(TaxonomicFilterGroupType.LogAttributes, null)])).toEqual([])
        expect(buildRecentFacets([recent(TaxonomicFilterGroupType.LogAttributes, '')])).toEqual([])
    })

    it('caps the number of recent facets', () => {
        const many = Array.from({ length: 25 }, (_, i) => recent(TaxonomicFilterGroupType.LogAttributes, `attr_${i}`))
        expect(buildRecentFacets(many)).toHaveLength(10)
    })
})
