import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import type { GroupBySourceEnumApi } from 'products/logs/frontend/generated/api.schemas'

// Maps the picker's taxonomic group onto the group-by endpoint's source vocabulary.
export const TAXONOMIC_GROUP_TO_SOURCE: Partial<Record<TaxonomicFilterGroupType, GroupBySourceEnumApi>> = {
    [TaxonomicFilterGroupType.Logs]: 'column',
    [TaxonomicFilterGroupType.LogAttributes]: 'log',
    [TaxonomicFilterGroupType.LogResourceAttributes]: 'resource',
}

// Top-level log fields that the endpoint groups by `source: 'column'` (backend `GROUPABLE_COLUMNS`).
// The same keys also surface in the Recent tab, where they were recorded under `LogAttributes` (the
// search bar stores them as filter type `log`). Trusting that group would send `source: 'log'`, so
// the aggregation reads a non-existent attribute map entry and returns nothing. Pin them to `column`
// by key so a recent groups by the real column, matching a fresh pick from the `Logs` group.
const GROUPABLE_COLUMN_KEYS = new Set<string>(['severity_level', 'trace_id', 'span_id'])

export function resolveGroupBySource(key: string, groupType: TaxonomicFilterGroupType): GroupBySourceEnumApi {
    if (GROUPABLE_COLUMN_KEYS.has(key)) {
        return 'column'
    }
    return TAXONOMIC_GROUP_TO_SOURCE[groupType] ?? 'log'
}
