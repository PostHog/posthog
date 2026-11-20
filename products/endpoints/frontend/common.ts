import { router } from 'kea-router'

import { PostHogComDocsURL } from 'lib/lemon-ui/Link/Link'
import { urls } from 'scenes/urls'

import { isHogQLQuery } from '~/queries/schema/node-guards'
import { NodeKind } from '~/queries/schema/schema-general'
import { EndpointType } from '~/types'

/** Must match ENDPOINT_NAME_REGEX in products/endpoints/backend/constants.py */
const ENDPOINT_NAME_REGEX = /^[a-zA-Z][a-zA-Z0-9_-]{0,127}$/

export function validateEndpointName(name: string): string | undefined {
    if (!name) {
        return 'Endpoint name is required'
    }
    if (name.length > 128) {
        return `Name is too long (${name.length}/128 characters).`
    }
    if (!/^[a-zA-Z]/.test(name)) {
        return 'Name must start with a letter.'
    }
    // Allow spaces (slugify converts them to hyphens) but catch truly unsupported chars like . , ! @ etc.
    const invalidChars = name.match(/[^a-zA-Z0-9_\s-]/g)
    if (invalidChars) {
        const unique = [...new Set(invalidChars)]
        return `Name contains unsupported characters: ${unique.map((c) => `"${c}"`).join(', ')}. Only letters, numbers, hyphens, and underscores are allowed.`
    }
    if (!ENDPOINT_NAME_REGEX.test(name) && !ENDPOINT_NAME_REGEX.test(name.replace(/\s+/g, '-'))) {
        return 'Name must start with a letter, contain only letters, numbers, hyphens, or underscores, and be between 1 and 128 characters.'
    }
    return undefined
}

/** SQL endpoints duplicate in the SQL editor. Every other kind duplicates through the insight modal. */
export function duplicateEndpointFromList(
    endpoint: EndpointType,
    openInsightDuplicateModal: (endpoint: EndpointType) => void
): void {
    if (isHogQLQuery(endpoint.query)) {
        router.actions.push(urls.sqlEditor({ query: endpoint.query.query, source: 'endpoint' }))
    } else {
        openInsightDuplicateModal(endpoint)
    }
}

/**
 * Converts a NodeKind query type to a user-friendly display name by removing the 'Query' suffix.
 * Examples: 'HogQLQuery' -> 'HogQL', 'TrendsQuery' -> 'Trends', 'FunnelsQuery' -> 'Funnels'
 */
export function humanizeQueryKind(kind: NodeKind | string): string {
    return kind.endsWith('Query') ? kind.slice(0, -5) : kind
}

export interface EndpointsDocs {
    url?: PostHogComDocsURL
    title: string
    description: string | JSX.Element
}
