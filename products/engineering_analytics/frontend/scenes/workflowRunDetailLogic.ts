import { afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import {
    engineeringAnalyticsRunFailureLogs,
    engineeringAnalyticsWorkflowJobs,
    engineeringAnalyticsWorkflowRun,
} from '../generated/api'
import type { RunFailureLogsApi, WorkflowJobApi, WorkflowRunDetailApi } from '../generated/api.schemas'
import { isDecisiveFailure } from '../lib/lifecycle'
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
        // null = not loaded, [] = source unsynced. Scoped to the run's actual attempt (loaded first) —
        // the backend's omitted-attempt fallback would otherwise show an older attempt's jobs/costs.
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
        // Fetched only for a decisively failed run; 'unavailable' = the fetch itself failed.
        failureLogs: [
            null as RunFailureLogsApi | 'unavailable' | null,
            {
                loadFailureLogs: async (): Promise<RunFailureLogsApi | 'unavailable'> => {
                    try {
                        return await engineeringAnalyticsRunFailureLogs(projectId(), {
                            run_id: props.runId,
                            source_id: props.sourceId ?? undefined,
                        })
                    } catch {
                        return 'unavailable'
                    }
                },
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
        sourceId: [() => [(_, p: WorkflowRunDetailLogicProps) => p.sourceId], (sourceId): string | null => sourceId],
        // Summed from the already-loaded jobs — no extra query.
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

    listeners(({ actions, values }) => ({
        // Load jobs only once the run is in, so they can be scoped to the run's real attempt.
        loadRunSuccess: () => {
            actions.loadJobs()
            // Failure logs only exist for failed runs — skip the query otherwise.
            if (isDecisiveFailure(values.run?.conclusion ?? null)) {
                actions.loadFailureLogs()
            }
        },
    })),

    afterMount(({ actions, props }) => {
        // A non-numeric run id would just 400; the scene renders "not found" instead.
        if (Number.isFinite(props.runId)) {
            actions.loadRun()
        }
    }),
])
