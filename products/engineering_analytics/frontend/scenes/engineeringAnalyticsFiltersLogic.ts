import { actions, kea, listeners, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import type { engineeringAnalyticsFiltersLogicType } from './engineeringAnalyticsFiltersLogicType'

// One window shared by every CI-analytics surface that's scoped by time — the Workflows tab, a single
// workflow's runs/cost page, and an author's cost tiles — so a window picked on one carries to the others
// instead of each page snapping back to its own default. 7 days balances the two needs the pages used to
// split on (-24h health vs -30d spend): long enough to read a week of spend, short enough that health still
// reads as recent. Nothing live is lost — the "is CI red now" verdict is window-independent and bucket
// granularity auto-follows the window, so narrowing to 24h still gives the live hourly view on demand.
export const SHARED_DEFAULT_DATE_FROM = '-7d'

// The branch scope is shared here too, alongside the window, so filtering to `master` on the Workflows tab
// carries into a workflow's detail page instead of the detail silently widening back to all branches (which
// read as "more runs" than the tab showed). It's a server-side filter (head_branch), so typing only stages
// the value in branchInput; applyBranchFilter promotes it to appliedBranch, which the consuming logics send.
export const engineeringAnalyticsFiltersLogic = kea<engineeringAnalyticsFiltersLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'engineeringAnalyticsFiltersLogic']),

    actions({
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setBranchFilter: (branch: string) => ({ branch }),
        applyBranchFilter: true,
        setAppliedBranch: (branch: string) => ({ branch }),
    }),

    reducers({
        dateFrom: [SHARED_DEFAULT_DATE_FROM as string | null, { setDateRange: (_, { dateFrom }) => dateFrom }],
        dateTo: [null as string | null, { setDateRange: (_, { dateTo }) => dateTo }],
        // branchInput is the staged text in the box; appliedBranch is what the consuming loaders send. '' means
        // all branches. appliedBranch persists across date reloads (e.g. "master on last 30d" → "last 90d").
        branchInput: ['', { setBranchFilter: (_, { branch }) => branch }],
        appliedBranch: ['', { setAppliedBranch: (_, { branch }) => branch }],
    }),

    listeners(({ actions, values }) => ({
        setBranchFilter: ({ branch }) => {
            // The search input's built-in clear (×) only fires onChange(''), never Enter/blur, so clearing it
            // would otherwise leave the tables scoped to the old branch. Apply on empty so the × resets to
            // all-branches immediately.
            if (branch.trim() === '') {
                actions.applyBranchFilter()
            }
        },
        applyBranchFilter: () => {
            const next = values.branchInput.trim()
            // Skip promoting (and the reload it triggers in consumers) when the box is unchanged.
            if (next === values.appliedBranch) {
                return
            }
            actions.setAppliedBranch(next)
        },
    })),

    actionToUrl(({ values }) => ({
        // Encode the window in the URL so tab links and drill-down links (which preserve query params) carry
        // it, and a shared link reopens it. Replace, not push — nudging a date shouldn't stack back-history.
        // The default is omitted so a pristine URL stays clean.
        setDateRange: () => {
            const { pathname, searchParams, hashParams } = router.values.currentLocation
            const next = { ...searchParams }
            if (values.dateFrom && values.dateFrom !== SHARED_DEFAULT_DATE_FROM) {
                next.date_from = values.dateFrom
            } else {
                delete next.date_from
            }
            if (values.dateTo) {
                next.date_to = values.dateTo
            } else {
                delete next.date_to
            }
            return [pathname, next, hashParams, { replace: true }]
        },
        // Mirror the applied branch into `?q=` so a branch-scoped view is shareable, survives reload, and
        // carries through drill-down links into the workflow detail page. Empty is omitted to keep URLs clean.
        setAppliedBranch: () => {
            const { pathname, searchParams, hashParams } = router.values.currentLocation
            const next = { ...searchParams }
            if (values.appliedBranch) {
                next.q = values.appliedBranch
            } else {
                delete next.q
            }
            return [pathname, next, hashParams, { replace: true }]
        },
    })),

    urlToAction(({ actions, values }) => ({
        // Hydrate from the URL on any CI-analytics route — a shared link, a reload, or a drill-down link that
        // carried the params. Guarded so we only dispatch on a real change, which also breaks the actionToUrl
        // loop. '*' is safe here: the logic is only mounted while a CI-analytics scene connects it, so this
        // never fires for unrelated routes. Handler params are inferred (kea-router types them).
        '*': (_, searchParams) => {
            const dateFrom = searchParams.date_from ?? SHARED_DEFAULT_DATE_FROM
            const dateTo = searchParams.date_to ?? null
            if (dateFrom !== values.dateFrom || dateTo !== values.dateTo) {
                actions.setDateRange(dateFrom, dateTo)
            }
            const branch = (searchParams.q ?? '').trim()
            if (branch !== values.appliedBranch) {
                actions.setBranchFilter(branch)
                // An empty value already applies via setBranchFilter's listener; a real branch needs the apply.
                if (branch !== '') {
                    actions.setAppliedBranch(branch)
                }
            }
        },
    })),
])
