import { afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { engineeringAnalyticsWorkflowJobs, engineeringAnalyticsWorkflowRun } from '../generated/api'
import type { WorkflowJobApi, WorkflowRunDetailApi } from '../generated/api.schemas'
import { RunCostSummary, summarizeRunCost } from '../lib/runHealth'
import type { workflowRunDetailLogicType } from './workflowRunDetailLogicType'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export interface WorkflowRunDetailLogicProps {
    repoOwner: string
    repoName: string
    runId: number
    // Which GitHub source the list was scoped to, threaded from `?source=` via paramsToProps.
    sourceId: string | null
}

export const workflowRunDetailLogic = kea<workflowRunDetailLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'workflowRunDetailLogic']),
    props({} as WorkflowRunDetailLogicProps),
    // sourceId is part of the identity: the same run id only exists within one source.
    key((props) => `${props.repoOwner}/${props.repoName}/runs/${props.runId}@${props.sourceId ?? ''}`),

    loaders(({ props, values }) => ({
        run: [
            null as WorkflowRunDetailApi | null,
            {
                loadRun: async (): Promise<WorkflowRunDetailApi | null> =>
                    await engineeringAnalyticsWorkflowRun(projectId(), {
                        run_id: props.runId,
                        source_id: props.sourceId ?? undefined,
                    }),
            },
        ],
        // A single run's jobs — the breakdown the PR view shows on expand. null while not loaded (kea
        // reducers can't hold undefined), [] when the source isn't synced. Scoped to the run's actual
        // attempt (loaded first): a rerun's jobs source can lag, and the backend's omitted-attempt fallback
        // would otherwise show an older attempt's jobs/costs.
        jobs: [
            null as WorkflowJobApi[] | null,
            {
                loadJobs: async (): Promise<WorkflowJobApi[]> =>
                    await engineeringAnalyticsWorkflowJobs(projectId(), {
                        run_id: props.runId,
                        run_attempt: values.run?.run_attempt ?? undefined,
                        source_id: props.sourceId ?? undefined,
                    }),
            },
        ],
    })),

    reducers({
        loadFailed: [
            false,
            {
                loadRun: () => false,
                loadRunSuccess: () => false,
                loadRunFailure: () => true,
            },
        ],
    }),

    selectors({
        // Exposed so the scene can preserve `?source=` when linking out to the PR detail.
        sourceId: [() => [(_, p: WorkflowRunDetailLogicProps) => p.sourceId], (sourceId): string | null => sourceId],
        // The run's own CI cost, summed from the jobs already loaded for the breakdown table — no extra
        // query. null until jobs load or when nothing on the run is billable. Mirrors the PR page's tile.
        runCost: [(s) => [s.jobs], (jobs): RunCostSummary | null => (jobs ? summarizeRunCost(jobs) : null)],
        // A non-numeric path segment yields NaN — the scene shows a clean "not found" instead of a load error.
        isValidRunId: [
            () => [(_, p: WorkflowRunDetailLogicProps) => p.runId],
            (runId): boolean => Number.isFinite(runId),
        ],
        breadcrumbs: [
            (_, p) => [p.repoOwner, p.repoName, p.runId],
            (repoOwner, repoName, runId): Breadcrumb[] => [
                {
                    key: 'EngineeringAnalytics',
                    name: 'Engineering analytics',
                    path: urls.engineeringAnalytics(),
                    iconType: 'health',
                },
                {
                    key: ['EngineeringAnalyticsWorkflowRun', `${repoOwner}/${repoName}/runs/${runId}`],
                    name: `${repoOwner}/${repoName} · run #${runId}`,
                    iconType: 'health',
                },
            ],
        ],
    }),

    listeners(({ actions }) => ({
        // Load jobs only once the run is in, so they can be scoped to the run's real attempt.
        loadRunSuccess: () => actions.loadJobs(),
    })),

    afterMount(({ actions, props }) => {
        // Skip the load for a non-numeric run id (NaN) — it would just 400; the scene renders "not found".
        // Jobs load on loadRunSuccess (needs the run's attempt first).
        if (Number.isFinite(props.runId)) {
            actions.loadRun()
        }
    }),
])
