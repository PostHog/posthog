import { actions, connect, kea, path, reducers, selectors } from 'kea'

import type { authorsListLogicType } from './authorsListLogicType'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import { AuthorStatsRow, computeAuthorStats } from './repoOverviewLogic'

// The authors list — the landing of the unvalued `author: any` lens chip. Derived client-side from the
// loaded PR list (the endpoint is capped, so this covers the most recent PRs, labeled as such).
export const authorsListLogic = kea<authorsListLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'authorsListLogic']),

    connect(() => ({
        values: [engineeringAnalyticsLogic, ['pullRequests', 'pullRequestsLoading']],
    })),

    actions({
        setAuthorSearch: (search: string) => ({ search }),
    }),

    reducers({
        authorSearch: ['', { setAuthorSearch: (_, { search }) => search }],
    }),

    selectors({
        authorRows: [
            (s) => [s.pullRequests, s.authorSearch],
            (pullRequests, authorSearch): AuthorStatsRow[] => {
                const search = authorSearch.trim().toLowerCase()
                return computeAuthorStats(pullRequests)
                    .filter((row) => !search || row.handle.toLowerCase().includes(search))
                    .sort((a, b) => b.prCount - a.prCount)
            },
        ],
    }),
])
