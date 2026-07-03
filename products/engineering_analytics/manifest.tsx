/** Product manifest for engineering_analytics: scenes, routes, URLs, and navigation. */
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
            name: 'Engineering analytics',
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
        EngineeringAnalyticsWorkflowRun: {
            import: () => import('./frontend/scenes/WorkflowRunDetailScene'),
            projectBased: true,
            name: 'Workflow run',
            layout: 'app-container',
            description: 'A single workflow run: status, duration, branch, and the attributed pull request.',
            iconType: 'health',
        },
        EngineeringAnalyticsWorkflowRuns: {
            import: () => import('./frontend/scenes/WorkflowRunsScene'),
            projectBased: true,
            name: 'Workflow runs',
            layout: 'app-container',
            description: "A single workflow's recent runs across the connected repo.",
            iconType: 'health',
        },
    },
    // Detail paths mirror GitHub 1:1 (owner/repo/pull/:n, owner/repo/actions/runs/:id); cross-repo
    // aggregates stay at the product root. Provider lives on the data (RepoRef.provider), so these url
    // builders are the single place to branch verbs for a future provider (e.g. GitLab).
    routes: {
        '/engineering-analytics': ['EngineeringAnalytics', 'engineeringAnalytics'],
        '/engineering-analytics/pulls': ['EngineeringAnalytics', 'engineeringAnalyticsPullRequestList'],
        '/engineering-analytics/workflows': ['EngineeringAnalytics', 'engineeringAnalyticsWorkflows'],
        '/engineering-analytics/test-health': ['EngineeringAnalytics', 'engineeringAnalyticsTestHealth'],
        '/engineering-analytics/:repoOwner/:repoName/pull/:number': [
            'EngineeringAnalyticsPullRequest',
            'engineeringAnalyticsPullRequest',
        ],
        '/engineering-analytics/:repoOwner/:repoName/actions/runs/:runId': [
            'EngineeringAnalyticsWorkflowRun',
            'engineeringAnalyticsWorkflowRun',
        ],
        '/engineering-analytics/:repoOwner/:repoName/actions/workflows/:workflowName': [
            'EngineeringAnalyticsWorkflowRuns',
            'engineeringAnalyticsWorkflowRuns',
        ],
    },
    redirects: {
        // The author surface was removed: analytics stay at team/repo level (see README locked decisions).
        '/engineering-analytics/authors': '/engineering-analytics',
        '/engineering-analytics/author/:handle': '/engineering-analytics',
    },
    urls: {
        engineeringAnalytics: (): string => '/engineering-analytics',
        engineeringAnalyticsPullRequestList: (): string => '/engineering-analytics/pulls',
        engineeringAnalyticsWorkflows: (): string => '/engineering-analytics/workflows',
        engineeringAnalyticsTestHealth: (): string => '/engineering-analytics/test-health',
        engineeringAnalyticsPullRequest: (repoOwner: string, repoName: string, number: number | string): string =>
            `/engineering-analytics/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/pull/${number}`,
        engineeringAnalyticsWorkflowRun: (repoOwner: string, repoName: string, runId: number | string): string =>
            `/engineering-analytics/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/actions/runs/${runId}`,
        engineeringAnalyticsWorkflowRuns: (repoOwner: string, repoName: string, workflowName: string): string =>
            `/engineering-analytics/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/actions/workflows/${encodeURIComponent(workflowName)}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Engineering analytics',
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
