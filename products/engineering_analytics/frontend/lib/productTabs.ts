import { urls } from 'scenes/urls'

import type { EngineeringAnalyticsView } from '../scenes/engineeringAnalyticsSceneLogic'

export interface ProductTab {
    key: EngineeringAnalyticsView
    label: string
    /** The tab's path inside a repository ('owner/name'). */
    url: (repo?: string | null) => string
    dataAttr: string
}

/** The product's top-level areas, in tab order. Detail pages render inside the tab they drill down from. */
export const PRODUCT_TABS: ProductTab[] = [
    { key: 'hub', label: 'Overview', url: urls.engineeringAnalytics, dataAttr: 'engineering-analytics-overview-tab' },
    {
        key: 'pull-requests',
        label: 'Pull requests',
        url: urls.engineeringAnalyticsPullRequestList,
        dataAttr: 'engineering-analytics-pull-requests-tab',
    },
    {
        key: 'workflows',
        label: 'Workflows',
        url: urls.engineeringAnalyticsWorkflows,
        dataAttr: 'engineering-analytics-workflows-tab',
    },
    {
        key: 'tests',
        label: 'Tests',
        url: urls.engineeringAnalyticsTests,
        // Pinned because autocapture dashboards and selectors use the original value.
        dataAttr: 'engineering-analytics-test-health-tab',
    },
    {
        key: 'deploys',
        label: 'Deploys',
        url: urls.engineeringAnalyticsDeploys,
        // Pinned because autocapture dashboards and selectors use the original value.
        dataAttr: 'engineering-analytics-health-tab',
    },
    { key: 'teams', label: 'Teams', url: urls.engineeringAnalyticsTeams, dataAttr: 'engineering-analytics-teams-tab' },
    {
        key: 'authors',
        label: 'Authors',
        url: urls.engineeringAnalyticsAuthors,
        dataAttr: 'engineering-analytics-authors-tab',
    },
]
