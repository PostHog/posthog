import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { engineeringAnalyticsPullRequests } from '../generated/api'
import type { PullRequestListItemApi } from '../generated/api.schemas'
import type { authorLogicType } from './authorLogicType'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export interface AuthorLogicProps {
    handle: string
    // Which GitHub source the list was scoped to, threaded from `?source=` via paramsToProps.
    sourceId: string | null
    tabId?: string
}

export const authorLogic = kea<authorLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'authorLogic']),
    props({} as AuthorLogicProps),
    key((props) => `${props.tabId ?? 'default'}/author/${props.handle}@${props.sourceId ?? ''}`),

    actions({
        // Window start for the list + cost. dateTo is unused (the list endpoint floors on date_from only).
        setDateFrom: (dateFrom: string) => ({ dateFrom }),
    }),

    reducers({
        // One window bounds both the PR list and the cost — open PRs always shown, finished ones since here.
        dateFrom: ['-30d', { setDateFrom: (_, { dateFrom }) => dateFrom }],
    }),

    loaders(({ props, values }) => ({
        prs: [
            [] as PullRequestListItemApi[],
            {
                loadPrs: async (): Promise<PullRequestListItemApi[]> => {
                    const result = await engineeringAnalyticsPullRequests(projectId(), {
                        author: props.handle,
                        date_from: values.dateFrom,
                        source_id: props.sourceId ?? undefined,
                    })
                    return result.items
                },
            },
        ],
    })),

    selectors({
        sourceId: [() => [(_, p: AuthorLogicProps) => p.sourceId], (sourceId): string | null => sourceId],
        handle: [() => [(_, p: AuthorLogicProps) => p.handle], (handle): string => handle],
        // Author totals across the visible PRs — null when nothing was costable / the job source is unsynced.
        totalCostUsd: [
            (s) => [s.prs],
            (prs: PullRequestListItemApi[]): number | null => {
                const costs = prs.map((pr) => pr.estimated_cost_usd).filter((c): c is number => c != null)
                return costs.length ? costs.reduce((sum, c) => sum + c, 0) : null
            },
        ],
        totalBillableMinutes: [
            (s) => [s.prs],
            (prs: PullRequestListItemApi[]): number | null => {
                const minutes = prs.map((pr) => pr.billable_minutes).filter((m): m is number => m != null)
                return minutes.length ? minutes.reduce((sum, m) => sum + m, 0) : null
            },
        ],
        breadcrumbs: [
            (_, p) => [p.handle],
            (handle): Breadcrumb[] => [
                {
                    key: 'EngineeringAnalytics',
                    name: 'CI analytics',
                    path: urls.engineeringAnalytics(),
                    iconType: 'health',
                },
                { key: ['EngineeringAnalyticsAuthor', handle], name: handle, iconType: 'health' },
            ],
        ],
    }),

    listeners(({ actions }) => ({
        setDateFrom: () => actions.loadPrs(),
    })),

    afterMount(({ actions }) => {
        actions.loadPrs()
    }),
])
