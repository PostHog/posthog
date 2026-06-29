import { actions, afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { engineeringAnalyticsPullRequests } from '../generated/api'
import type { authorLogicType } from './authorLogicType'
import { PullRequestRow, toPullRequestRow } from './engineeringAnalyticsLogic'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

// The PR list itself isn't date-scoped (the date picker only scopes the cost tiles), but the load still
// needs a floor for finished PRs — a wide one so the list reads as "this author's recent PRs". Open PRs
// come back regardless of this. Wider than any tile window option, so the tiles are always a subset.
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

    actions({
        // Window for the cost tiles only — the PR list below is not re-scoped by it.
        setDateFrom: (dateFrom: string) => ({ dateFrom }),
    }),

    reducers({
        // Tile window; default last 30 days. Drives the client-side filter in `windowedRows`, never a reload.
        dateFrom: ['-30d', { setDateFrom: (_, { dateFrom }) => dateFrom }],
    }),

    loaders(({ props }) => ({
        prs: [
            [] as PullRequestRow[],
            {
                // Loaded once: the author's recent PRs, mapped to the shared table row shape. Stable across
                // date changes — the date picker only scopes the tiles.
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
    })),

    selectors({
        sourceId: [() => [(_, p: AuthorLogicProps) => p.sourceId], (sourceId): string | null => sourceId],
        handle: [() => [(_, p: AuthorLogicProps) => p.handle], (handle): string => handle],
        // The tile scope: PRs opened within the selected window. The list shows every loaded PR; only the
        // cost KPIs narrow to this subset, so the date picker reads as "cost of PRs opened in the last N days".
        windowedRows: [
            (s) => [s.prs, s.dateFrom],
            (prs: PullRequestRow[], dateFrom: string): PullRequestRow[] => {
                const cutoff = dateStringToDayJs(dateFrom)
                if (!cutoff) {
                    return prs
                }
                return prs.filter((pr) => dayjs(pr.createdAt).isAfter(cutoff))
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
    }),
])
