import { PostHogComDocsURL } from 'lib/lemon-ui/Link/Link'

import { NodeKind } from '~/queries/schema/schema-general'

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
