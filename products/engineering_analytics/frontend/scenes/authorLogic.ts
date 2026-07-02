import { afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { engineeringAnalyticsAuthorWorkflowCosts, engineeringAnalyticsPullRequests } from '../generated/api'
import type { WorkflowCostApi } from '../generated/api.schemas'
import type { authorLogicType } from './authorLogicType'
import { engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
import { PullRequestRow, toPullRequestRow } from './engineeringAnalyticsLogic'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

// The PR list isn't date-scoped (the picker only scopes the cost tiles), but the load needs a floor for
// finished PRs — wide so the list reads as "this author's recent PRs", and wider than any tile window so
// the tiles stay a subset. Open PRs come back regardless.
const LIST_WINDOW = '-365d'

export interface AuthorLogicProps {
    handle: string
    // Which GitHub source the list was scoped to, threaded from `?source=` via paramsToProps.
    sourceId: string | null
}

export const authorLogic = kea<authorLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'authorLogic']),
    props({} as AuthorLogicProps),
    key((props) => `author/${props.handle}@${props.sourceId ?? ''}`),

    // Shares the CI-analytics window, but only to scope the cost tiles (a client-side filter over the
    // already-loaded PRs) — the PR list below is never re-scoped, so changing the window never reloads here.
    connect(() => ({
        values: [engineeringAnalyticsFiltersLogic, ['dateFrom', 'dateTo']],
    })),

    loaders(({ props, values }) => ({
        prs: [
            [] as PullRequestRow[],
            {
                // Loaded once: the author's recent PRs, mapped to the shared table row shape. Stable across
                // date changes — the picker only scopes the tiles.
                loadPrs: async (): Promise<PullRequestRow[]> => {
                    const result = await engineeringAnalyticsPullRequests(projectId(), {
                        author: props.handle,
                        date_from: LIST_WINDOW,
                        source_id: props.sourceId ?? undefined,
                    })
                    return result.items.map(toPullRequestRow)
                },
            },
        ],
        // The author's CI spend split by workflow over the shared window — "where their CI minutes go".
        // [] when the job-level source isn't synced.
        workflowCosts: [
            [] as WorkflowCostApi[],
            {
                loadWorkflowCosts: async (): Promise<WorkflowCostApi[]> =>
                    await engineeringAnalyticsAuthorWorkflowCosts(projectId(), {
                        author: props.handle,
                        date_from: values.dateFrom ?? undefined,
                        date_to: values.dateTo ?? undefined,
                        source_id: props.sourceId ?? undefined,
                    }),
            },
        ],
    })),

    listeners(({ actions }) => ({
        // The shared window scopes the cost breakdown — reload it when the picker changes.
        [engineeringAnalyticsFiltersLogic.actionTypes.setDateRange]: () => {
            actions.loadWorkflowCosts()
        },
    })),

    selectors({
        sourceId: [() => [(_, p: AuthorLogicProps) => p.sourceId], (sourceId): string | null => sourceId],
        handle: [() => [(_, p: AuthorLogicProps) => p.handle], (handle): string => handle],
        // The tile scope: PRs opened within the selected window. The list shows every loaded PR; only the
        // cost KPIs narrow to this subset, so the date picker reads as "cost of PRs opened in the window".
        windowedRows: [
            (s) => [s.prs, s.dateFrom, s.dateTo],
            (prs: PullRequestRow[], dateFrom: string | null, dateTo: string | null): PullRequestRow[] => {
                const from = dateFrom ? dateStringToDayJs(dateFrom) : null
                const to = dateTo ? dateStringToDayJs(dateTo) : null
                return prs.filter((pr) => {
                    const created = dayjs(pr.createdAt)
                    return (!from || created.isAfter(from)) && (!to || created.isBefore(to))
                })
            },
        ],
        // Author totals across the in-window PRs — null when nothing was costable / the job source is unsynced.
        totalCostUsd: [
            (s) => [s.windowedRows],
            (rows: PullRequestRow[]): number | null => {
                const costs = rows.map((pr) => pr.estimatedCostUsd).filter((c): c is number => c != null)
                return costs.length ? costs.reduce((sum, c) => sum + c, 0) : null
            },
        ],
        totalBillableMinutes: [
            (s) => [s.windowedRows],
            (rows: PullRequestRow[]): number | null => {
                const minutes = rows.map((pr) => pr.billableMinutes).filter((m): m is number => m != null)
                return minutes.length ? minutes.reduce((sum, m) => sum + m, 0) : null
            },
        ],
        // Median open→merge over the in-window merged PRs — this author's cycle-time headline.
        medianOpenToMergeSeconds: [
            (s) => [s.windowedRows],
            (rows: PullRequestRow[]): number | null => {
                const merged = rows
                    .map((pr) => pr.openToMergeSeconds)
                    .filter((seconds): seconds is number => seconds != null)
                    .sort((a, b) => a - b)
                if (!merged.length) {
                    return null
                }
                const mid = Math.floor(merged.length / 2)
                return merged.length % 2 ? merged[mid] : (merged[mid - 1] + merged[mid]) / 2
            },
        ],
        rerunCycles: [
            (s) => [s.windowedRows],
            (rows: PullRequestRow[]): number => rows.reduce((sum, pr) => sum + pr.rerunCycles, 0),
        ],
        openPrCount: [
            (s) => [s.prs],
            (prs: PullRequestRow[]): number => prs.filter((pr) => pr.state === 'open').length,
        ],
        breadcrumbs: [
            (_, p) => [p.handle],
            (handle): Breadcrumb[] => [
                {
                    key: 'EngineeringAnalytics',
                    name: 'Engineering analytics',
                    path: urls.engineeringAnalytics(),
                    iconType: 'health',
                },
                { key: ['EngineeringAnalyticsAuthor', handle], name: handle, iconType: 'health' },
            ],
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadPrs()
        actions.loadWorkflowCosts()
    }),
])
