import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { AnyPropertyFilter, PropertyFilterType } from '~/types'

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

/** The audience a link asked for, or null when it is missing or not a list of person or cohort filters. */
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
    const valid = value.every(
        (filter) =>
            filter &&
            typeof filter === 'object' &&
            typeof filter.key === 'string' &&
            AUDIENCE_FILTER_TYPES.includes(filter.type)
    )
    return valid ? (value as AnyPropertyFilter[]) : null
}
