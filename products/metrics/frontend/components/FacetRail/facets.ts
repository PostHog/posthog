import { FacetGroupItem } from 'lib/components/FacetRail/facetGroups'

import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyFilterValue,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { SERVICE_NAME_KEY } from '../../metricsAttributes'

export interface MetricFacetConfig extends FacetGroupItem {
    /** The metric attribute key the facet lists values for and filters on. */
    attributeKey: string
}

// The backend reads both spellings from the service column, so they share one facet.
const SERVICE_KEYS = new Set([SERVICE_NAME_KEY, 'service.name'])

const SERVICE_FACET: MetricFacetConfig = {
    key: 'service',
    title: 'Service',
    group: 'Standard',
    attributeKey: SERVICE_NAME_KEY,
}

/** The service facet, then one facet per other attribute key, in the order the endpoint ranks them. */
export function buildMetricFacets(attributeKeys: string[]): MetricFacetConfig[] {
    const attributeFacets = Array.from(new Set(attributeKeys))
        .filter((key) => !SERVICE_KEYS.has(key))
        .map((key) => ({ key: `attribute:${key}`, title: key, group: 'Attributes', attributeKey: key }))
    return [SERVICE_FACET, ...attributeFacets]
}

interface MetricFacetFilter {
    key: string
    type: PropertyFilterType
    operator: PropertyOperator
    value?: PropertyFilterValue
}

export interface MetricFacetSelection {
    included: string[]
    excluded: string[]
}

// A clause filterGroup is { AND, values: [{ AND, values: [<chips>] }] }, and the filter bar edits the inner group.
function innerFilters(group: UniversalFiltersGroup): MetricFacetFilter[] {
    return ((group.values[0] as UniversalFiltersGroup | undefined)?.values ?? []) as MetricFacetFilter[]
}

// The rail owns the `exact` and `is_not` chips on its key. Other chips on the same key, such as a
// regex, stay as the filter bar wrote them. The service facet owns chips on both service spellings,
// so a `service.name` chip from the filter bar does not stay beside a contradicting rail chip.
function isRailFilter(filter: MetricFacetFilter, attributeKey: string): boolean {
    const sameKey = SERVICE_KEYS.has(attributeKey) ? SERVICE_KEYS.has(filter.key) : filter.key === attributeKey
    return (
        filter.type === PropertyFilterType.MetricAttribute &&
        sameKey &&
        (filter.operator === PropertyOperator.Exact || filter.operator === PropertyOperator.IsNot)
    )
}

function filterValues(filter: MetricFacetFilter): string[] {
    const values = Array.isArray(filter.value) ? filter.value : filter.value == null ? [] : [filter.value]
    return values.map(String).filter((value) => value !== '')
}

export function metricFacetSelection(group: UniversalFiltersGroup, attributeKey: string): MetricFacetSelection {
    const railFilters = innerFilters(group).filter((filter) => isRailFilter(filter, attributeKey))
    return {
        included: railFilters.filter((f) => f.operator === PropertyOperator.Exact).flatMap(filterValues),
        excluded: railFilters.filter((f) => f.operator === PropertyOperator.IsNot).flatMap(filterValues),
    }
}

/** Moves `value` one step through unchecked → included → excluded → unchecked, and returns a new filterGroup. */
export function cycleMetricFacetFilter(
    group: UniversalFiltersGroup,
    attributeKey: string,
    value: string
): UniversalFiltersGroup {
    const { included, excluded } = metricFacetSelection(group, attributeKey)
    let nextIncluded = included
    let nextExcluded = excluded
    if (included.includes(value)) {
        nextIncluded = included.filter((v) => v !== value)
        nextExcluded = [...excluded, value]
    } else if (excluded.includes(value)) {
        nextExcluded = excluded.filter((v) => v !== value)
    } else {
        nextIncluded = [...included, value]
    }

    const values = innerFilters(group).filter((filter) => !isRailFilter(filter, attributeKey))
    for (const [operator, selection] of [
        [PropertyOperator.Exact, nextIncluded],
        [PropertyOperator.IsNot, nextExcluded],
    ] as const) {
        if (selection.length > 0) {
            values.push({ key: attributeKey, type: PropertyFilterType.MetricAttribute, operator, value: selection })
        }
    }
    return { type: FilterLogicalOperator.And, values: [{ type: FilterLogicalOperator.And, values: values as any }] }
}
