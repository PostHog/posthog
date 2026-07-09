import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import type { GroupBySourceEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { resolveGroupBySource } from './groupBySource'

describe('resolveGroupBySource', () => {
    // A recent for a top-level column is recorded under LogAttributes (the search bar stores it as
    // filter type `log`), so trusting the group would send source `log` and the aggregation reads a
    // missing attribute -> empty results. These keys must resolve to `column` regardless of group.
    it.each<[string, TaxonomicFilterGroupType, GroupBySourceEnumApi]>([
        ['severity_level', TaxonomicFilterGroupType.LogAttributes, 'column'],
        ['trace_id', TaxonomicFilterGroupType.LogAttributes, 'column'],
        ['span_id', TaxonomicFilterGroupType.LogAttributes, 'column'],
        ['severity_level', TaxonomicFilterGroupType.Logs, 'column'],
        ['some.attribute', TaxonomicFilterGroupType.LogAttributes, 'log'],
        ['host.name', TaxonomicFilterGroupType.LogResourceAttributes, 'resource'],
        ['some.attribute', TaxonomicFilterGroupType.Logs, 'column'],
    ])('resolves %s from %s to %s', (key, groupType, expected) => {
        expect(resolveGroupBySource(key, groupType)).toBe(expected)
    })
})
