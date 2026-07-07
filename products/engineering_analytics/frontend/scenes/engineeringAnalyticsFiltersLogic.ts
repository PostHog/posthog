import { actions, kea, listeners, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import type { engineeringAnalyticsFiltersLogicType } from './engineeringAnalyticsFiltersLogicType'

// One window shared by every time-scoped CI-analytics surface, so a window picked on one page carries
// to the others. 7 days: long enough to read a week of spend, short enough that health reads as recent.
export const SHARED_DEFAULT_DATE_FROM = '-7d'

// The branch scope is shared the same way. It's a server-side filter (head_branch): typing stages
// branchInput; applyBranchFilter promotes it to appliedBranch, which the consuming logics send.
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
            // The input's clear (×) only fires onChange('') — apply on empty so it resets to all branches.
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
        // Replace, not push — nudging a date shouldn't stack back-history. Defaults are omitted.
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
        // Mirror the applied branch into `?q=` so a branch-scoped view is shareable and survives reload.
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
        // Hydrate from the URL, dispatching only on real change (also breaks the actionToUrl loop).
        // '*' is safe: the logic is only mounted while a CI-analytics scene connects it.
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
