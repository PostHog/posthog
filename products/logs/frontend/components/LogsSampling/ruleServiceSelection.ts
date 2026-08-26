/**
 * The rule editors' service selection, stored in the rule's own filter group as the same
 * `{key: 'service_name', type: 'log'}` column filter the logs viewer writes — so the ingestion
 * matcher, the ClickHouse query builder, and the preview all read it through paths they already
 * have, and a rule filter means exactly what the same chip means in the viewer.
 */
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import {
    SERVICE_NAME_FILTER,
    facetSelection,
    setFacetIncluded,
} from 'products/logs/frontend/components/LogsViewer/FacetRail/facetFilters'

// The facetFilters helpers walk the viewer's `{AND, values: [inner]}` wrapper; the rule editors
// hold the inner group itself (rules persist it unwrapped). Adapt at this boundary alone, so the
// selection semantics — one filter per polarity, other chips untouched — stay defined in one place.
const wrap = (inner: UniversalFiltersGroup): UniversalFiltersGroup => ({
    type: FilterLogicalOperator.And,
    values: [inner],
})

/** The services a rule's filter group includes, read from its `exact` service filter. */
export function ruleServiceNames(inner: UniversalFiltersGroup): string[] {
    return facetSelection(wrap(inner), SERVICE_NAME_FILTER).included
}

/** Replace the included services in a rule's filter group, leaving every other filter in place. */
export function withRuleServiceNames(inner: UniversalFiltersGroup, serviceNames: string[]): UniversalFiltersGroup {
    return setFacetIncluded(wrap(inner), SERVICE_NAME_FILTER, serviceNames).values[0] as UniversalFiltersGroup
}
