import { connect, kea, key, path, props, selectors } from 'kea'

import {
    RecentTaxonomicFilter,
    recentTaxonomicFiltersLogic,
} from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { FACETS, FacetConfig, MapAttributeSourceType } from './facets'
import type { logsFacetsLogicType } from './logsFacetsLogicType'

export interface LogsFacetsLogicProps {
    id: string
}

/** How many recently-used filters to surface as facets, most-recent first. */
const MAX_RECENT_FACETS = 10

// Recently-used taxonomic filters from these groups map cleanly onto map-backed facets — a resource
// attribute key or a log attribute key, both faceted server-side via the facet_values endpoint.
const RECENT_FACET_SOURCE_BY_GROUP: Partial<Record<TaxonomicFilterGroupType, MapAttributeSourceType>> = {
    [TaxonomicFilterGroupType.LogResourceAttributes]: 'resourceAttribute',
    [TaxonomicFilterGroupType.LogAttributes]: 'logAttribute',
}

function recentFacetKey(sourceType: MapAttributeSourceType, attributeKey: string): string {
    return `recent:${sourceType}:${attributeKey}`
}

/** Build dynamic "Recent" facets from recently-used logs filters, deduped by source + key. */
export function buildRecentFacets(recentFilters: RecentTaxonomicFilter[]): FacetConfig[] {
    const facets: FacetConfig[] = []
    const seen = new Set<string>()
    for (const filter of recentFilters) {
        const sourceType = RECENT_FACET_SOURCE_BY_GROUP[filter.groupType]
        const attributeKey = filter.value != null ? String(filter.value) : ''
        if (!sourceType || !attributeKey) {
            continue
        }
        const key = recentFacetKey(sourceType, attributeKey)
        if (seen.has(key)) {
            continue
        }
        seen.add(key)
        facets.push({
            key,
            title: attributeKey,
            group: 'Recent',
            kind: 'dynamic',
            source: { type: sourceType, key: attributeKey },
            searchable: true,
            searchPlaceholder: `Search ${attributeKey}…`,
            emptyLabel: 'No values',
            maxHeight: 300,
        })
        if (facets.length >= MAX_RECENT_FACETS) {
            break
        }
    }
    return facets
}

/** The full facet list for the rail: the standard facets plus dynamic facets for recently-used filters. */
export const logsFacetsLogic = kea<logsFacetsLogicType>([
    props({ id: 'default' } as LogsFacetsLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'logs', 'frontend', 'components', 'LogsViewer', 'FacetRail', 'logsFacetsLogic', key]),

    connect(() => ({
        values: [recentTaxonomicFiltersLogic, ['recentFilters']],
    })),

    selectors({
        recentFacets: [
            (s) => [s.recentFilters],
            (recentFilters: RecentTaxonomicFilter[]): FacetConfig[] => buildRecentFacets(recentFilters),
        ],
        facets: [(s) => [s.recentFacets], (recentFacets: FacetConfig[]): FacetConfig[] => [...FACETS, ...recentFacets]],
    }),
])
