import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { EngineeringAnalyticsWorkflowHealthRunScope } from '../generated/api.schemas'
import type { engineeringAnalyticsFiltersLogicType } from './engineeringAnalyticsFiltersLogicType'

// One window shared by every time-scoped CI-analytics surface, so a window picked on one page carries
// to the others. 7 days: long enough to read a week of spend, short enough that health reads as recent.
export const SHARED_DEFAULT_DATE_FROM = '-7d'

// The "non-default branch" lens: PR-attributed runs with the default branch (master/main) excluded.
const PR_SCOPE = EngineeringAnalyticsWorkflowHealthRunScope.PullRequest

// The workflow-health request params the active branch scope resolves to. `run_scope` is workflow_health's
// alone; every other surface reads `appliedBranch` (which the PR lens leaves empty, so they fall back to
// all branches). Owning the scope→params mapping here means no consumer re-derives which param to send.
export interface BranchHealthParams {
    branch?: string
    run_scope?: typeof PR_SCOPE
}

// The branch scope is shared like the window. An exact branch is a server-side head_branch filter; the PR
// lens is a run_scope. The two are mutually exclusive — the reducers keep an invalid "branch + lens" state
// from ever existing — so a page only ever sees one of them.
export const engineeringAnalyticsFiltersLogic = kea<engineeringAnalyticsFiltersLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'engineeringAnalyticsFiltersLogic']),

    actions({
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setBranchFilter: (branch: string) => ({ branch }),
        applyBranchFilter: true,
        setAppliedBranch: (branch: string) => ({ branch }),
        // The "non-default branch" lens: PR-attributed runs, default branch (master/main) excluded.
        scopeToPullRequests: true,
    }),

    reducers({
        dateFrom: [SHARED_DEFAULT_DATE_FROM as string | null, { setDateRange: (_, { dateFrom }) => dateFrom }],
        dateTo: [null as string | null, { setDateRange: (_, { dateTo }) => dateTo }],
        // branchInput is the staged text in the box; appliedBranch is what exact-branch consumers send. ''
        // means all branches; the PR lens clears both, since it's mutually exclusive with an exact branch.
        branchInput: [
            '',
            {
                setBranchFilter: (_, { branch }) => branch,
                scopeToPullRequests: () => '',
            },
        ],
        appliedBranch: [
            '',
            {
                setAppliedBranch: (_, { branch }) => branch,
                scopeToPullRequests: () => '',
            },
        ],
        // Applying any exact branch — including clearing to all — turns the PR lens off.
        pullRequestScope: [
            false,
            {
                scopeToPullRequests: () => true,
                setAppliedBranch: () => false,
            },
        ],
    }),

    selectors({
        branchHealthParams: [
            (s) => [s.appliedBranch, s.pullRequestScope],
            (appliedBranch, pullRequestScope): BranchHealthParams =>
                pullRequestScope ? { run_scope: PR_SCOPE } : appliedBranch ? { branch: appliedBranch } : {},
        ],
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
            // Skip promoting (and the reload it triggers) when nothing changes — unless the PR lens is on,
            // which an exact branch must clear.
            if (next === values.appliedBranch && !values.pullRequestScope) {
                return
            }
            actions.setAppliedBranch(next)
        },
    })),

    actionToUrl(({ values }) => ({
        // Replace, not push — nudging a scope shouldn't stack back-history. Defaults are omitted.
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
        // Mirror the exact branch into `?q=` so a branch-scoped view is shareable; drop the mutually
        // exclusive PR lens.
        setAppliedBranch: () => {
            const { pathname, searchParams, hashParams } = router.values.currentLocation
            const next = { ...searchParams }
            if (values.appliedBranch) {
                next.q = values.appliedBranch
            } else {
                delete next.q
            }
            delete next.run_scope
            return [pathname, next, hashParams, { replace: true }]
        },
        scopeToPullRequests: () => {
            const { pathname, searchParams, hashParams } = router.values.currentLocation
            const next = { ...searchParams }
            next.run_scope = PR_SCOPE
            delete next.q
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
            if (searchParams.run_scope === PR_SCOPE) {
                if (!values.pullRequestScope) {
                    actions.scopeToPullRequests()
                }
                return
            }
            const branch = (searchParams.q ?? '').trim()
            if (branch !== values.appliedBranch || values.pullRequestScope) {
                actions.setBranchFilter(branch)
                // An empty value already applies via setBranchFilter's listener; a real branch needs the apply.
                if (branch !== '') {
                    actions.setAppliedBranch(branch)
                }
            }
        },
    })),
])
