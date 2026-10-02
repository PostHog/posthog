import {
    FacetSearchValue,
    FacetValueOption,
    ServerFacet,
    parseFacetSearch,
    toFacetQuery,
} from 'lib/components/FacetSearchBar/facetSearch'

import type { MessageCategoryApi } from 'products/messaging/frontend/generated/api.schemas'

// pinned: facet keys and values are the listing API's `filter` grammar and live in shared URLs
const ALL_MARKETING: FacetValueOption = { value: 'all-marketing', label: 'All marketing' }

const SUPPRESSION_SOURCES: FacetValueOption[] = [
    { value: 'BOUNCE', label: 'Bounces' },
    { value: 'COMPLAINT', label: 'Spam report' },
    { value: 'MANUAL', label: 'Added manually' },
]

function topicValues(topics: MessageCategoryApi[]): FacetValueOption[] {
    const marketingTopics = topics.filter((topic) => topic.category_type === 'marketing')
    return [ALL_MARKETING, ...marketingTopics.map((topic) => ({ value: topic.key, label: topic.name }))]
}

export function recipientFacets(topics: MessageCategoryApi[]): ServerFacet[] {
    const topicOptions = topicValues(topics)
    return [
        {
            key: 'subscribed',
            label: 'Subscribed to',
            description: 'Recorded as subscribed to a topic',
            showOnFocus: true,
            order: 1,
            values: topicOptions,
        },
        {
            key: 'unsubscribed',
            label: 'Unsubscribed from',
            description: 'Recorded as unsubscribed from a topic',
            showOnFocus: true,
            order: 2,
            values: topicOptions,
        },
        {
            key: 'no-preference',
            label: 'No preference on',
            description: 'Nothing recorded for a topic',
            showOnFocus: true,
            order: 3,
            values: topicOptions,
        },
        {
            key: 'suppressed',
            label: 'Suppressed',
            description: 'Never sent to, and why',
            showOnFocus: true,
            order: 4,
            values: SUPPRESSION_SOURCES,
        },
        {
            key: 'person',
            label: 'Person',
            description: 'Whether a person holds this address',
            showOnFocus: true,
            order: 5,
            values: [
                { value: 'linked', label: 'Linked' },
                { value: 'none', label: 'No person' },
            ],
        },
        {
            key: 'preference',
            label: 'Preference',
            description: 'Whether any preference was ever recorded',
            order: 6,
            values: [
                { value: 'recorded', label: 'Recorded' },
                { value: 'none', label: 'None recorded' },
            ],
        },
    ]
}

const FACET_KEYS_ONLY = recipientFacets([])

export function parseRecipientSearch(query: string): FacetSearchValue {
    return parseFacetSearch(query, FACET_KEYS_ONLY)
}

/** One `facet:value` per value, `-facet:value` when negated, the way the listing API's repeated `filter` reads them. */
export function recipientFilterParams(value: FacetSearchValue): string[] {
    return Object.entries(toFacetQuery(value).facets).flatMap(([facet, { include, exclude }]) => [
        ...include.map((facetValue) => `${facet}:${facetValue}`),
        ...exclude.map((facetValue) => `-${facet}:${facetValue}`),
    ])
}

export function facetKeysInUse(value: FacetSearchValue): string[] {
    return Object.keys(toFacetQuery(value).facets).sort()
}
