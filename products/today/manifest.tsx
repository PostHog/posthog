/**
 * Product manifest for today.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { combineUrl } from 'kea-router'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Today',
    scenes: {
        TaskSpaces: {
            name: 'Spaces',
            import: () => import('./frontend/spaces/SpacesScene'),
            projectBased: true,
        },
        TaskNewSession: {
            name: 'New session',
            import: () => import('./frontend/spaces/NewSessionScene'),
            projectBased: true,
        },
        TaskSpace: {
            name: 'Space',
            import: () => import('./frontend/spaces/SpaceScene'),
            projectBased: true,
        },
    },
    routes: {
        '/spaces': ['TaskSpaces', 'taskSpaces'],
        '/ai/new': ['TaskNewSession', 'taskNewSession'],
        '/spaces/:id': ['TaskSpace', 'taskSpace'],
        '/spaces/:id/canvases': ['TaskSpace', 'taskSpaceCanvases'],
        '/spaces/:id/new': ['TaskNewSession', 'taskSpaceNewSession'],
        '/spaces/:id/settings': ['TaskSpace', 'taskSpaceSettings'],
    },
    redirects: {
        '/spaces/new': (_params, searchParams, hashParams): string =>
            combineUrl('/ai/new', searchParams, hashParams).url,
    },
    urls: {
        taskSpaces: (): string => '/spaces',
        taskNewSession: (): string => '/ai/new',
        taskSpace: (id: string): string => `/spaces/${id}`,
        taskSpaceCanvases: (id: string): string => `/spaces/${id}/canvases`,
        taskSpaceNewSession: (id: string): string => `/spaces/${id}/new`,
        taskSpaceSettings: (id: string): string => `/spaces/${id}/settings`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
