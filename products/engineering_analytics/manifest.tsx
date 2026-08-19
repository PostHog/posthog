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
        EngineeringAnalyticsTeam: {
            import: () => import('./frontend/scenes/EngineeringAnalyticsTeamScene'),
            projectBased: true,
            name: 'Team CI health',
            layout: 'app-container',
            description: "One owning team's merge timing and the before/after signal on its owned tests.",
            iconType: 'health',
        },
    },
    // Repository paths follow GitHub's owner/repo shape while using provider-neutral, plural resource names.
    routes: {
        '/engineering-analytics/overview': ['EngineeringAnalytics', 'engineeringAnalytics'],
        '/engineering-analytics/pulls': ['EngineeringAnalytics', 'engineeringAnalyticsPullRequestList'],
        '/engineering-analytics/workflows': ['EngineeringAnalytics', 'engineeringAnalyticsWorkflows'],
        '/engineering-analytics/test-health': ['EngineeringAnalytics', 'engineeringAnalyticsTestHealth'],
        '/engineering-analytics/teams': ['EngineeringAnalytics', 'engineeringAnalyticsTeams'],
        '/engineering-analytics/teams/:ownerTeam': ['EngineeringAnalyticsTeam', 'engineeringAnalyticsTeam'],
        '/engineering-analytics/:repoOwner/:repoName/pulls/:number': [
            'EngineeringAnalyticsPullRequest',
            'engineeringAnalyticsPullRequest',
        ],
        '/engineering-analytics/:repoOwner/:repoName/workflow-runs/:runId': [
            'EngineeringAnalyticsWorkflowRun',
            'engineeringAnalyticsWorkflowRun',
        ],
        '/engineering-analytics/:repoOwner/:repoName/workflows/:workflowName': [
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
        engineeringAnalyticsPullRequestList: (): string => '/engineering-analytics/pulls',
        engineeringAnalyticsWorkflows: (): string => '/engineering-analytics/workflows',
        engineeringAnalyticsTestHealth: (): string => '/engineering-analytics/test-health',
        engineeringAnalyticsTeams: (): string => '/engineering-analytics/teams',
        engineeringAnalyticsTeam: (ownerTeam: string): string =>
            `/engineering-analytics/teams/${encodeURIComponent(ownerTeam)}`,
        engineeringAnalyticsPullRequest: (repoOwner: string, repoName: string, number: number | string): string =>
            `/engineering-analytics/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/pulls/${number}`,
        engineeringAnalyticsWorkflowRun: (repoOwner: string, repoName: string, runId: number | string): string =>
            `/engineering-analytics/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/workflow-runs/${runId}`,
        engineeringAnalyticsWorkflowRuns: (repoOwner: string, repoName: string, workflowName: string): string =>
            `/engineering-analytics/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/workflows/${encodeURIComponent(workflowName)}`,
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
