import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

// pinned: URL search params, other products link to /broadcasts/new with these
export const AUDIENCE_PREFILL_PARAM = 'audience'
export const NAME_PREFILL_PARAM = 'name'
export const SOURCE_PREFILL_PARAM = 'source'

export interface BroadcastPrefill {
    properties: AnyPropertyFilter[]
    name?: string
    /** The product surface the person came from, reported on the launch event. */
    source?: string
}

export function urlForNewBroadcastWithAudience({ properties, name, source }: BroadcastPrefill): string {
    return combineUrl(urls.broadcastNew(), {
        [AUDIENCE_PREFILL_PARAM]: JSON.stringify(properties),
        ...(name ? { [NAME_PREFILL_PARAM]: name } : {}),
        ...(source ? { [SOURCE_PREFILL_PARAM]: source } : {}),
    }).url
}

/** The audience a link asked for, or null when it is missing or any filter in it can't be applied. */
export function parseBroadcastAudiencePrefill(raw: unknown): AnyPropertyFilter[] | null {
    let value = raw
    if (typeof raw === 'string') {
        try {
            value = JSON.parse(raw)
        } catch {
            return null
        }
    }
    if (!Array.isArray(value) || value.length === 0) {
        return null
    }
    const filters = value.map(toAudienceFilter)
    return filters.every((filter): filter is AnyPropertyFilter => filter !== null) ? filters : null
}

const PERSON_OPERATORS: string[] = Object.values(PropertyOperator)
const COHORT_OPERATORS: string[] = [PropertyOperator.In, PropertyOperator.NotIn]

function isFilterValue(value: unknown): boolean {
    return (
        typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value)) || typeof value === 'boolean'
    )
}

// Rebuilt from known fields only: the backend drops a filter with a field it rejects, which would widen the
// audience to everyone while the wizard still shows the filter.
function toAudienceFilter(filter: unknown): AnyPropertyFilter | null {
    if (!filter || typeof filter !== 'object' || Array.isArray(filter)) {
        return null
    }
    const { key, type, operator, value, cohort_name } = filter as Record<string, unknown>
    if (typeof key !== 'string' || key === '') {
        return null
    }
    if (type === PropertyFilterType.Cohort) {
        if (key !== 'id' || typeof value !== 'number' || !Number.isInteger(value) || value <= 0) {
            return null
        }
        if (operator !== undefined && (typeof operator !== 'string' || !COHORT_OPERATORS.includes(operator))) {
            return null
        }
        return {
            key: 'id',
            type: PropertyFilterType.Cohort,
            value,
            operator: (operator as PropertyOperator | undefined) ?? PropertyOperator.In,
            ...(typeof cohort_name === 'string' ? { cohort_name } : {}),
        }
    }
    if (type !== PropertyFilterType.Person || typeof operator !== 'string' || !PERSON_OPERATORS.includes(operator)) {
        return null
    }
    if (operator === PropertyOperator.IsSet || operator === PropertyOperator.IsNotSet) {
        return { key, type: PropertyFilterType.Person, operator: operator as PropertyOperator }
    }
    const hasValue = Array.isArray(value)
        ? value.length > 0 && value.every(isFilterValue)
        : isFilterValue(value) && value !== ''
    if (!hasValue) {
        return null
    }
    return {
        key,
        type: PropertyFilterType.Person,
        operator: operator as PropertyOperator,
        value: value as string | number | boolean | (string | number | boolean)[],
    } as AnyPropertyFilter
}
