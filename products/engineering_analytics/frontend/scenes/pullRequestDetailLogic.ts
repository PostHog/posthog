import { afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { engineeringAnalyticsPrLifecycle } from '../generated/api'
import type { PRLifecycleApi } from '../generated/api.schemas'
import { LifecycleSummary, WorkflowRun, isPassingConclusion, summarizeLifecycle, workflowRuns } from '../lib/lifecycle'
import type { pullRequestDetailLogicType } from './pullRequestDetailLogicType'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export interface PullRequestDetailLogicProps {
    repoOwner: string
    repoName: string
    number: number
    // Which GitHub source the list was scoped to, threaded from `?source=` via paramsToProps.
    sourceId: string | null
    tabId?: string
}

/** Failures first, then still-running, then passes — the order a reviewer triages in. */
export function sortRunsForTriage(runs: WorkflowRun[]): WorkflowRun[] {
    const rank = (run: WorkflowRun): number =>
        run.conclusion === null ? 1 : isPassingConclusion(run.conclusion) ? 2 : 0
    return [...runs].sort((a, b) => rank(a) - rank(b) || a.workflow.localeCompare(b.workflow))
}

export const pullRequestDetailLogic = kea<pullRequestDetailLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'pullRequestDetailLogic']),
    props({} as PullRequestDetailLogicProps),
    // sourceId is part of the identity: the same PR number can resolve to a different source.
    key(
        (props) =>
            `${props.tabId ?? 'default'}/${props.repoOwner}/${props.repoName}#${props.number}@${props.sourceId ?? ''}`
    ),

    loaders(({ props }) => ({
        lifecycle: [
            null as PRLifecycleApi | null,
            {
                loadLifecycle: async (): Promise<PRLifecycleApi | null> =>
                    await engineeringAnalyticsPrLifecycle(projectId(), {
                        pr_number: props.number,
                        repo: `${props.repoOwner}/${props.repoName}`,
                        source_id: props.sourceId ?? undefined,
                    }),
            },
        ],
    })),

    reducers({
        loadFailed: [
            false,
            {
                loadLifecycle: () => false,
                loadLifecycleSuccess: () => false,
                loadLifecycleFailure: () => true,
            },
        ],
    }),

    selectors({
        summary: [
            (s) => [s.lifecycle],
            (lifecycle): LifecycleSummary | null => (lifecycle ? summarizeLifecycle(lifecycle.events) : null),
        ],
        runs: [
            (s) => [s.lifecycle],
            (lifecycle): WorkflowRun[] => (lifecycle ? sortRunsForTriage(workflowRuns(lifecycle.events)) : []),
        ],
        breadcrumbs: [
            (_, p) => [p.repoOwner, p.repoName, p.number],
            (repoOwner, repoName, number): Breadcrumb[] => [
                {
                    key: 'EngineeringAnalytics',
                    name: 'CI analytics',
                    path: urls.engineeringAnalytics(),
                    iconType: 'health',
                },
                {
                    key: ['EngineeringAnalyticsPullRequest', `${repoOwner}/${repoName}#${number}`],
                    name: `${repoOwner}/${repoName} #${number}`,
                    iconType: 'health',
                },
            ],
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadLifecycle()
    }),
])
