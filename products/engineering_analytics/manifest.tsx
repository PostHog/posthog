/**
 * Product manifest for engineering_analytics.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'EngineeringAnalytics',
    scenes: {
        EngineeringAnalytics: {
            import: () => import('./frontend/scenes/EngineeringAnalyticsScene'),
            projectBased: true,
            name: 'CI analytics',
            layout: 'app-container',
            description: 'Pull request and workflow CI health across connected GitHub repos.',
            iconType: 'health',
        },
        EngineeringAnalyticsPullRequest: {
            import: () => import('./frontend/scenes/PullRequestDetailScene'),
            projectBased: true,
            name: 'Pull request',
            layout: 'app-container',
            description: 'A single pull request: lifecycle milestones and CI runs on its head commit.',
            iconType: 'health',
        },
    },
    routes: {
        '/engineering-analytics': ['EngineeringAnalytics', 'engineeringAnalytics'],
        '/engineering-analytics/workflows': ['EngineeringAnalytics', 'engineeringAnalyticsWorkflows'],
        '/engineering-analytics/test-health': ['EngineeringAnalytics', 'engineeringAnalyticsTestHealth'],
        '/engineering-analytics/pr/:repoOwner/:repoName/:number': [
            'EngineeringAnalyticsPullRequest',
            'engineeringAnalyticsPullRequest',
        ],
    },
    redirects: {},
    urls: {
        engineeringAnalytics: (): string => '/engineering-analytics',
        engineeringAnalyticsWorkflows: (): string => '/engineering-analytics/workflows',
        engineeringAnalyticsTestHealth: (): string => '/engineering-analytics/test-health',
        engineeringAnalyticsPullRequest: (repoOwner: string, repoName: string, number: number | string): string =>
            `/engineering-analytics/pr/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/${number}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'CI analytics',
            intents: [ProductKey.ENGINEERING_ANALYTICS],
            category: ProductItemCategory.UNRELEASED,
            type: 'engineering_analytics',
            iconType: 'health' as FileSystemIconType,
            iconColor: ['var(--color-product-data-warehouse-light)'] as FileSystemIconColor,
            href: urls.engineeringAnalytics(),
            flag: FEATURE_FLAGS.ENGINEERING_ANALYTICS,
            tags: ['alpha'],
            sceneKey: 'EngineeringAnalytics',
        },
    ],
}
