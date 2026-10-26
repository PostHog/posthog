/** Product manifest for engineering_analytics: scenes, routes, URLs, and navigation. */
import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'EngineeringAnalytics',
    scenes: {
        EngineeringAnalytics: {
            import: () => import('./frontend/scenes/EngineeringAnalyticsScene'),
            projectBased: true,
            name: 'Engineering analytics',
            layout: 'app-container',
            description: 'Pull requests, workflows, tests, deploys, and teams across connected GitHub repos.',
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
        EngineeringAnalyticsCIExplorer: {
            import: () => import('./frontend/scenes/CIExplorerScene'),
            projectBased: true,
            name: 'CI explorer',
            layout: 'app-container',
            description: "A pull request's CI on one zoomable canvas: workflows, jobs, and matrix shards.",
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
            name: 'Team',
            layout: 'app-container',
            description: "One owning team's merge timing and the before/after signal on its owned tests.",
            iconType: 'health',
        },
    },
    // Every page reads one repository, so the repository is a path segment on every page, shaped like
    // GitHub's REST API (repos/:owner/:repo/pull-requests/:n, .../actions/runs/:id). The repo-less tab
    // paths still route: the scene logic forwards them to a repository (the `?repo` they carry, else the
    // last one used, else the default), so old links and the product root keep working. Provider lives on
    // the data (RepoRef.provider), so these url builders are the single place to branch verbs for a
    // future provider (e.g. GitLab).
    routes: {
        '/engineering-analytics/overview': ['EngineeringAnalytics', 'engineeringAnalytics'],
        '/engineering-analytics/pull-requests': ['EngineeringAnalytics', 'engineeringAnalyticsPullRequestList'],
        '/engineering-analytics/workflows': ['EngineeringAnalytics', 'engineeringAnalyticsWorkflows'],
        '/engineering-analytics/tests': ['EngineeringAnalytics', 'engineeringAnalyticsTests'],
        '/engineering-analytics/teams': ['EngineeringAnalytics', 'engineeringAnalyticsTeams'],
        '/engineering-analytics/authors': ['EngineeringAnalytics', 'engineeringAnalyticsAuthors'],
        '/engineering-analytics/deploys': ['EngineeringAnalytics', 'engineeringAnalyticsDeploys'],
        '/engineering-analytics/teams/:ownerTeam': ['EngineeringAnalyticsTeam', 'engineeringAnalyticsTeam'],
        '/engineering-analytics/authors/:handle': ['EngineeringAnalyticsAuthor', 'engineeringAnalyticsAuthor'],
        '/engineering-analytics/repos/:repoOwner/:repoName/overview': ['EngineeringAnalytics', 'engineeringAnalytics'],
        '/engineering-analytics/repos/:repoOwner/:repoName/pull-requests': [
            'EngineeringAnalytics',
            'engineeringAnalyticsPullRequestList',
        ],
        '/engineering-analytics/repos/:repoOwner/:repoName/workflows': [
            'EngineeringAnalytics',
            'engineeringAnalyticsWorkflows',
        ],
        '/engineering-analytics/repos/:repoOwner/:repoName/tests': [
            'EngineeringAnalytics',
            'engineeringAnalyticsTests',
        ],
        '/engineering-analytics/repos/:repoOwner/:repoName/teams': [
            'EngineeringAnalytics',
            'engineeringAnalyticsTeams',
        ],
        '/engineering-analytics/repos/:repoOwner/:repoName/authors': [
            'EngineeringAnalytics',
            'engineeringAnalyticsAuthors',
        ],
        '/engineering-analytics/repos/:repoOwner/:repoName/deploys': [
            'EngineeringAnalytics',
            'engineeringAnalyticsDeploys',
        ],
        '/engineering-analytics/repos/:repoOwner/:repoName/teams/:ownerTeam': [
            'EngineeringAnalyticsTeam',
            'engineeringAnalyticsTeam',
        ],
        '/engineering-analytics/repos/:repoOwner/:repoName/authors/:handle': [
            'EngineeringAnalyticsAuthor',
            'engineeringAnalyticsAuthor',
        ],
        '/engineering-analytics/repos/:repoOwner/:repoName/pull-requests/:number': [
            'EngineeringAnalyticsPullRequest',
            'engineeringAnalyticsPullRequest',
        ],
        '/engineering-analytics/repos/:repoOwner/:repoName/pull-requests/:number/ci-explorer': [
            'EngineeringAnalyticsCIExplorer',
            'engineeringAnalyticsCIExplorer',
        ],
        '/engineering-analytics/repos/:repoOwner/:repoName/actions/runs/:runId': [
            'EngineeringAnalyticsWorkflowRun',
            'engineeringAnalyticsWorkflowRun',
        ],
        '/engineering-analytics/repos/:repoOwner/:repoName/actions/workflows/:workflowName': [
            'EngineeringAnalyticsWorkflowRuns',
            'engineeringAnalyticsWorkflowRuns',
        ],
    },
    redirects: {
        // Bare product root lands on the overview tab without dropping its scope.
        '/engineering-analytics': (_params, searchParams, hashParams): string =>
            combineUrl(urls.engineeringAnalytics(), searchParams, hashParams).url,
        '/engineering-analytics/test-health': (_params, searchParams, hashParams): string =>
            combineUrl(urls.engineeringAnalyticsTests(), searchParams, hashParams).url,
        '/engineering-analytics/health': (_params, searchParams, hashParams): string =>
            combineUrl(urls.engineeringAnalyticsDeploys(), searchParams, hashParams).url,
    },
    // Tab and team/author builders take the 'owner/name' in scope. Without one they return the repo-less
    // path, which forwards to a repository, so a caller outside the product never has to pick one.
    // The paths are written out because the app URL catalog evaluates these builders without imports.
    urls: {
        engineeringAnalytics: (repo?: string | null): string =>
            repo
                ? `/engineering-analytics/repos/${repo.split('/').map(encodeURIComponent).join('/')}/overview`
                : '/engineering-analytics/overview',
        engineeringAnalyticsPullRequestList: (repo?: string | null): string =>
            repo
                ? `/engineering-analytics/repos/${repo.split('/').map(encodeURIComponent).join('/')}/pull-requests`
                : '/engineering-analytics/pull-requests',
        engineeringAnalyticsWorkflows: (repo?: string | null): string =>
            repo
                ? `/engineering-analytics/repos/${repo.split('/').map(encodeURIComponent).join('/')}/workflows`
                : '/engineering-analytics/workflows',
        engineeringAnalyticsTests: (repo?: string | null): string =>
            repo
                ? `/engineering-analytics/repos/${repo.split('/').map(encodeURIComponent).join('/')}/tests`
                : '/engineering-analytics/tests',
        engineeringAnalyticsTeams: (repo?: string | null): string =>
            repo
                ? `/engineering-analytics/repos/${repo.split('/').map(encodeURIComponent).join('/')}/teams`
                : '/engineering-analytics/teams',
        engineeringAnalyticsAuthors: (repo?: string | null): string =>
            repo
                ? `/engineering-analytics/repos/${repo.split('/').map(encodeURIComponent).join('/')}/authors`
                : '/engineering-analytics/authors',
        engineeringAnalyticsDeploys: (repo?: string | null): string =>
            repo
                ? `/engineering-analytics/repos/${repo.split('/').map(encodeURIComponent).join('/')}/deploys`
                : '/engineering-analytics/deploys',
        engineeringAnalyticsTeam: (ownerTeam: string, repo?: string | null): string =>
            `${repo ? `/engineering-analytics/repos/${repo.split('/').map(encodeURIComponent).join('/')}` : '/engineering-analytics'}/teams/${encodeURIComponent(ownerTeam)}`,
        engineeringAnalyticsPullRequest: (repoOwner: string, repoName: string, number: number | string): string =>
            `/engineering-analytics/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/pull-requests/${number}`,
        engineeringAnalyticsCIExplorer: (repoOwner: string, repoName: string, number: number | string): string =>
            `/engineering-analytics/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/pull-requests/${number}/ci-explorer`,
        engineeringAnalyticsWorkflowRun: (
            repoOwner: string,
            repoName: string,
            runId: number | string,
            ciEngine?: string | null
        ): string =>
            `/engineering-analytics/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/actions/runs/${runId}${ciEngine ? `?ci_engine=${encodeURIComponent(ciEngine)}` : ''}`,
        engineeringAnalyticsWorkflowRuns: (repoOwner: string, repoName: string, workflowName: string): string =>
            `/engineering-analytics/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}/actions/workflows/${encodeURIComponent(workflowName)}`,
        engineeringAnalyticsAuthor: (handle: string, repo?: string | null): string =>
            `${repo ? `/engineering-analytics/repos/${repo.split('/').map(encodeURIComponent).join('/')}` : '/engineering-analytics'}/authors/${encodeURIComponent(handle)}`,
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
            iconColor: [
                'var(--color-product-engineering-analytics-light)',
                'var(--color-product-engineering-analytics-dark)',
            ],
            href: urls.engineeringAnalytics(),
            searchKeywords: ['ci', 'ci health', 'ci cost', 'github actions', 'build minutes', 'dora', 'cycle time'],
            searchTabs: [
                { name: 'Pull requests', href: urls.engineeringAnalyticsPullRequestList() },
                { name: 'CI workflows', href: urls.engineeringAnalyticsWorkflows() },
                { name: 'Tests', href: urls.engineeringAnalyticsTests(), searchKeywords: ['flaky tests'] },
                { name: 'Deploys', href: urls.engineeringAnalyticsDeploys() },
                { name: 'Teams', href: urls.engineeringAnalyticsTeams() },
                { name: 'Authors', href: urls.engineeringAnalyticsAuthors() },
            ],
            flag: FEATURE_FLAGS.ENGINEERING_ANALYTICS,
            tags: ['alpha'],
            sceneKey: 'EngineeringAnalytics',
        },
    ],
}
