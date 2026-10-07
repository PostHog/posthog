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

const AUDIENCE_FILTER_TYPES: string[] = [PropertyFilterType.Person, PropertyFilterType.Cohort]

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
    return value.every(isUsableAudienceFilter) ? (value as AnyPropertyFilter[]) : null
}

// A filter the backend can't apply is dropped there, which would widen the audience to everyone.
function isUsableAudienceFilter(filter: unknown): boolean {
    if (!filter || typeof filter !== 'object') {
        return false
    }
    const { key, type, operator, value } = filter as Record<string, unknown>
    if (typeof key !== 'string' || typeof type !== 'string' || !AUDIENCE_FILTER_TYPES.includes(type)) {
        return false
    }
    if (type === PropertyFilterType.Cohort) {
        return typeof value === 'number' && Number.isFinite(value)
    }
    if (operator === PropertyOperator.IsSet || operator === PropertyOperator.IsNotSet) {
        return true
    }
    return value !== undefined && value !== null && value !== '' && !(Array.isArray(value) && value.length === 0)
}
