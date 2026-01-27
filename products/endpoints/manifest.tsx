import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'

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
        EndpointScene: {
            import: () => import('./frontend/EndpointScene'),
            projectBased: true,
            name: 'Endpoint',
            activityScope: 'Endpoint',
        },
    },
    routes: {
        '/endpoints': ['EndpointsScene', 'endpoints'],
        '/endpoints/usage': ['EndpointsScene', 'endpointsUsage'],
        '/endpoints/:name': ['EndpointScene', 'endpoint'],
    },
    urls: {
        endpoints: (): string => '/endpoints',
        endpoint: (name: string): string => `/endpoints/${name}`,
        endpointsUsage: (params?: {
            endpointFilter?: string[]
            dateFrom?: string
            dateTo?: string
            materializationType?: 'materialized' | 'inline'
            interval?: string
            breakdownBy?: string
        }): string => {
            if (!params) {
                return '/endpoints/usage'
            }
            const searchParams: Record<string, string> = {}
            if (params.endpointFilter?.length) {
                searchParams.endpointFilter = params.endpointFilter.join(',')
            }
            if (params.dateFrom) {
                searchParams.dateFrom = params.dateFrom
            }
            if (params.dateTo) {
                searchParams.dateTo = params.dateTo
            }
            if (params.materializationType) {
                searchParams.materializationType = params.materializationType
            }
            if (params.interval) {
                searchParams.interval = params.interval
            }
            if (params.breakdownBy) {
                searchParams.breakdownBy = params.breakdownBy
            }
            return combineUrl('/endpoints/usage', searchParams).url
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
            intents: [ProductKey.ENDPOINTS],
            category: 'Unreleased',
            href: urls.endpoints(),
            type: 'endpoints',
            flag: FEATURE_FLAGS.ENDPOINTS,
            tags: ['beta'],
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
            tags: ['beta'],
        },
    ],
}
