import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import type { MessagingNavTabKey } from '../messagingTabs'

export type TransactionalTab = 'transactional' | 'log' | 'metrics'
export type TransactionalRoute = MessagingNavTabKey | TransactionalTab | 'new'

/** The view a URL opens in the Transactional scene, or null for a URL that belongs to another scene. */
export function transactionalRouteFor(pathname: string): TransactionalRoute | null {
    const match = removeProjectIdIfPresent(pathname).match(/^\/transactional(?:\/([^/]+))?\/?$/)
    if (!match) {
        return null
    }
    // The manifest only sends literal paths to this scene, so a single segment is always one of its views.
    return (match[1] ?? 'transactional') as TransactionalRoute
}
