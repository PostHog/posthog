import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Endpoints',
    scenes: {
        EndpointsScene: {
            import: () => import('./frontend/EndpointsScene'),
            projectBased: true,
            name: 'Endpoints',
            activityScope: 'Endpoints',
            layout: 'app-container',
            defaultDocsPath: '/docs/endpoints',
            iconType: 'endpoints',
            description: 'Define queries your application will use via the API and monitor their cost and usage.',
        },
        EndpointsUsage: {
            import: () => import('./frontend/EndpointsUsage'),
            projectBased: true,
            name: 'Endpoints usage',
            activityScope: 'Endpoints',
            layout: 'app-container',
            iconType: 'endpoints',
        },
        EndpointScene: {
            import: () => import('./frontend/EndpointScene'),
            projectBased: true,
            name: 'Endpoint',
            activityScope: 'Endpoint',
        },
        EndpointNew: {
            import: () => import('./frontend/EndpointScene'),
            projectBased: true,
            name: 'EndpointNew',
            activityScope: 'Endpoint',
        },
    },
    routes: {
        '/endpoints': ['EndpointsScene', 'endpoints'],
        // EndpointsScene stays first as scene for Usage!
        '/endpoints/usage': ['EndpointsScene', 'endpointsUsage'],
        '/endpoints/:name': ['EndpointScene', 'endpoint'],
        '/endpoints/new': ['EndpointNew', 'endpointNew'],
    },
    urls: {
        endpoints: (): string => '/endpoints',
        endpoint: (name: string): string => `/endpoints/${name}`,
        endpointsUsage: (params?: {
            dateFrom?: string
            dateTo?: string
            requestNameBreakdownEnabled?: string
            requestNameFilter?: string[]
        }): string => {
            const queryParams = new URLSearchParams(params as Record<string, string>)
            const stringifiedParams = queryParams.toString()
            return `/endpoints/usage${stringifiedParams ? `?${stringifiedParams}` : ''}`
        },
    },
    fileSystemTypes: {
        endpoints: {
            name: 'Endpoints',
            iconType: 'endpoints',
            href: () => urls.endpoints(),
            iconColor: ['var(--color-product-endpoints-light)'],
            filterKey: 'endpoints',
            flag: FEATURE_FLAGS.ENDPOINTS,
        },
    },
    treeItemsProducts: [
        {
            path: 'Endpoints',
            category: 'Unreleased',
            href: urls.endpoints(),
            type: 'endpoints',
            flag: FEATURE_FLAGS.ENDPOINTS,
            tags: ['alpha'],
            iconType: 'endpoints',
            iconColor: ['var(--color-product-endpoints-light)'] as FileSystemIconColor,
            sceneKey: 'EndpointsScene',
        },
    ],
    treeItemsMetadata: [
        {
            path: 'Endpoints',
            category: 'Unreleased',
            iconType: 'endpoints' as FileSystemIconType,
            iconColor: ['var(--color-product-endpoints-light)'] as FileSystemIconColor,
            href: urls.endpoints(),
            sceneKey: 'EndpointsScene',
            flag: FEATURE_FLAGS.ENDPOINTS,
            tags: ['alpha'],
        },
    ],
}
