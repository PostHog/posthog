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
        EngineeringAnalyticsAuthor: {
            import: () => import('./frontend/scenes/EngineeringAnalyticsAuthorScene'),
            projectBased: true,
            name: 'Author',
            layout: 'app-container',
            description: "One author's pull requests — a filtered view for finding work, not a ranking.",
            iconType: 'health',
        },
    },
    // Detail paths follow GitHub's REST-API shape (repos/:owner/:repo/pull-requests/:n, .../actions/runs/:id)
    // — a repos/ prefix that keeps them clear of the tab routes and readable collection nouns. Cross-repo
    // aggregates stay at the product root. Provider lives on the data (RepoRef.provider), so these url
    // builders are the single place to branch verbs for a future provider (e.g. GitLab).
    routes: {
        '/engineering-analytics/overview': ['EngineeringAnalytics', 'engineeringAnalytics'],
        '/engineering-analytics/pull-requests': ['EngineeringAnalytics', 'engineeringAnalyticsPullRequestList'],
        '/engineering-analytics/workflows': ['EngineeringAnalytics', 'engineeringAnalyticsWorkflows'],
        '/engineering-analytics/test-health': ['EngineeringAnalytics', 'engineeringAnalyticsTestHealth'],
        '/engineering-analytics/repos/:repoOwner/:repoName/pull-requests/:number': [
            'EngineeringAnalyticsPullRequest',
            'engineeringAnalyticsPullRequest',
        ],
        '/engineering-analytics/repos/:repoOwner/:repoName/actions/runs/:runId': [
            'EngineeringAnalyticsWorkflowRun',
            'engineeringAnalyticsWorkflowRun',
        ],
        '/engineering-analytics/repos/:repoOwner/:repoName/actions/workflows/:workflowName': [
            'EngineeringAnalyticsWorkflowRuns',
            'engineeringAnalyticsWorkflowRuns',
        ],
        '/engineering-analytics/authors/:handle': ['EngineeringAnalyticsAuthor', 'engineeringAnalyticsAuthor'],
    },
    redirects: {
        // Bare product root lands on the overview tab.
        '/engineering-analytics': '/engineering-analytics/overview',
        // The author *list* (leaderboards / rankings) stays removed — analytics aggregate at team/repo
        // level only (see README locked decisions). The per-author page is a filtered PR view, reachable
        // only via the author links on PR rows, so it keeps its route above.
        '/engineering-analytics/authors': '/engineering-analytics/overview',
    },
    urls: {
        engineeringAnalytics: (): string => '/engineering-analytics/overview',
        engineeringAnalyticsPullRequestList: (): string => '/engineering-analytics/pull-requests',
        engineeringAnalyticsWorkflows: (): string => '/engineering-analytics/workflows',
        engineeringAnalyticsTestHealth: (): string => '/engineering-analytics/test-health',
        engineeringAnalyticsPullRequest: (repoOwner: string, repoName: string, number: number | string): string =>
            `/engineering-analytics/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/pull-requests/${number}`,
        engineeringAnalyticsWorkflowRun: (repoOwner: string, repoName: string, runId: number | string): string =>
            `/engineering-analytics/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/actions/runs/${runId}`,
        engineeringAnalyticsWorkflowRuns: (repoOwner: string, repoName: string, workflowName: string): string =>
            `/engineering-analytics/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/actions/workflows/${encodeURIComponent(workflowName)}`,
        engineeringAnalyticsAuthor: (handle: string): string =>
            `/engineering-analytics/authors/${encodeURIComponent(handle)}`,
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
