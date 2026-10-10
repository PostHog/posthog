import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from 'lib/components/PropertyFilters/utils'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { PropertyFilterType, PropertyOperator } from '~/types'
import type { AnyPropertyFilter } from '~/types'

import { filterValueKind, filterValueList } from './filterOperatorOptions'

const OPERATOR_PHRASES: Partial<Record<PropertyOperator, string>> = {
    [PropertyOperator.Exact]: 'is',
    [PropertyOperator.IsNot]: 'is not',
    [PropertyOperator.IContains]: 'contains',
    [PropertyOperator.NotIContains]: 'does not contain',
    [PropertyOperator.IContainsMulti]: 'contains',
    [PropertyOperator.NotIContainsMulti]: 'does not contain',
    [PropertyOperator.StartsWith]: 'starts with',
    [PropertyOperator.NotStartsWith]: 'does not start with',
    [PropertyOperator.EndsWith]: 'ends with',
    [PropertyOperator.NotEndsWith]: 'does not end with',
    [PropertyOperator.Regex]: 'matches',
    [PropertyOperator.NotRegex]: 'does not match',
    [PropertyOperator.GreaterThan]: 'is more than',
    [PropertyOperator.GreaterThanOrEqual]: 'is at least',
    [PropertyOperator.LessThan]: 'is less than',
    [PropertyOperator.LessThanOrEqual]: 'is at most',
    [PropertyOperator.IsSet]: 'is set',
    [PropertyOperator.IsNotSet]: 'is not set',
    [PropertyOperator.IsDateExact]: 'is on',
    [PropertyOperator.IsDateBefore]: 'is before',
    [PropertyOperator.IsDateAfter]: 'is after',
    [PropertyOperator.Between]: 'is between',
    [PropertyOperator.NotBetween]: 'is not between',
    [PropertyOperator.In]: 'is in',
    [PropertyOperator.NotIn]: 'is not in',
    [PropertyOperator.IsCleanedPathExact]: 'is',
    [PropertyOperator.FlagEvaluatesTo]: 'evaluates to',
    [PropertyOperator.SemverEq]: 'is version',
    [PropertyOperator.SemverNeq]: 'is not version',
    [PropertyOperator.SemverGt]: 'is newer than version',
    [PropertyOperator.SemverGte]: 'is at least version',
    [PropertyOperator.SemverLt]: 'is older than version',
    [PropertyOperator.SemverLte]: 'is at most version',
}

const RANGE_OPERATORS: PropertyOperator[] = [PropertyOperator.Between, PropertyOperator.NotBetween]

const ELEMENT_LABELS: Record<string, string> = {
    text: 'Element text',
    href: 'Element link',
    selector: 'Element selector',
    tag_name: 'Element tag',
}

/** A phrase lists at most this many values, and counts the rest. */
const MAX_LISTED_VALUES = 3

function listValues(values: string[]): string {
    if (values.length <= 1) {
        return values[0] ?? ''
    }
    if (values.length > MAX_LISTED_VALUES) {
        const listed = values.slice(0, MAX_LISTED_VALUES - 1)
        return `${listed.join(', ')} or ${values.length - listed.length} more`
    }
    return `${values.slice(0, -1).join(', ')} or ${values[values.length - 1]}`
}

function propertyLabel(filter: AnyPropertyFilter): string {
    if (filter.type === PropertyFilterType.Element) {
        return ELEMENT_LABELS[filter.key] ?? 'Element'
    }
    const groupType = filter.type ? PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[filter.type] : undefined
    const coreLabel = groupType && filter.key ? getCoreFilterDefinition(filter.key, groupType)?.label : undefined
    return coreLabel || ('label' in filter && filter.label) || filter.key || 'A property'
}

/** One filter as a short phrase, such as "Browser is Chrome", to read inside a sentence. */
export function describeFilter(filter: AnyPropertyFilter): string {
    if (filter.type === PropertyFilterType.Cohort) {
        const lead = filter.operator === PropertyOperator.NotIn ? 'not in' : 'in'
        return filter.cohort_name ? `${lead} the cohort ${filter.cohort_name}` : `${lead} a cohort`
    }
    if (filter.type === PropertyFilterType.HogQL) {
        return 'a SQL condition'
    }
    if (filter.type === PropertyFilterType.Behavioral) {
        const lead = filter.negation ? 'did not do' : 'did'
        return filter.event_type === 'events' && filter.key ? `${lead} ${filter.key}` : `${lead} a chosen action`
    }
    if (!filter.key) {
        return 'an unfinished filter'
    }

    const operator = ('operator' in filter && filter.operator) || PropertyOperator.Exact
    const phrase = OPERATOR_PHRASES[operator] ?? operator.replace(/_/g, ' ')
    const label = propertyLabel(filter)
    if (filterValueKind(operator, filter.value) === 'none') {
        return `${label} ${phrase}`
    }
    const values = filterValueList(filter.value)
    const listed = RANGE_OPERATORS.includes(operator) && values.length === 2 ? values.join(' and ') : listValues(values)
    return listed ? `${label} ${phrase} ${listed}` : `${label} ${phrase}`
}
