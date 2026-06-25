import { afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { engineeringAnalyticsWorkflowRunnerCosts, engineeringAnalyticsWorkflowRuns } from '../generated/api'
import type { WorkflowRunDetailApi, WorkflowRunnerCostApi } from '../generated/api.schemas'
import type { workflowRunsLogicType } from './workflowRunsLogicType'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export interface WorkflowRunsLogicProps {
    repoOwner: string
    repoName: string
    workflowName: string
    // Which GitHub source the list was scoped to, threaded from `?source=` via paramsToProps.
    sourceId: string | null
    tabId?: string
}

export const workflowRunsLogic = kea<workflowRunsLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'workflowRunsLogic']),
    props({} as WorkflowRunsLogicProps),
    key(
        (props) =>
            `${props.tabId ?? 'default'}/${props.repoOwner}/${props.repoName}/${props.workflowName}@${props.sourceId ?? ''}`
    ),

    loaders(({ props }) => ({
        runs: [
            [] as WorkflowRunDetailApi[],
            {
                loadRuns: async (): Promise<WorkflowRunDetailApi[]> =>
                    await engineeringAnalyticsWorkflowRuns(projectId(), {
                        workflow_name: props.workflowName,
                        repo: `${props.repoOwner}/${props.repoName}`,
                        source_id: props.sourceId ?? undefined,
                    }),
            },
        ],
        // Cost split by runner tier — "where this workflow's spend goes"; [] when jobs aren't synced.
        runnerCosts: [
            [] as WorkflowRunnerCostApi[],
            {
                loadRunnerCosts: async (): Promise<WorkflowRunnerCostApi[]> =>
                    await engineeringAnalyticsWorkflowRunnerCosts(projectId(), {
                        workflow_name: props.workflowName,
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
                loadRuns: () => false,
                loadRunsSuccess: () => false,
                loadRunsFailure: () => true,
            },
        ],
    }),

    selectors({
        // Pass props through as values so the scene reads the repo/workflow identity (for the title and
        // links) without reaching into logic internals, and can preserve `?source=` on outbound links.
        sourceId: [() => [(_, p: WorkflowRunsLogicProps) => p.sourceId], (sourceId): string | null => sourceId],
        repoOwner: [() => [(_, p: WorkflowRunsLogicProps) => p.repoOwner], (repoOwner): string => repoOwner],
        repoName: [() => [(_, p: WorkflowRunsLogicProps) => p.repoName], (repoName): string => repoName],
        workflowName: [
            () => [(_, p: WorkflowRunsLogicProps) => p.workflowName],
            (workflowName): string => workflowName,
        ],
        breadcrumbs: [
            (_, p) => [p.repoOwner, p.repoName, p.workflowName],
            (repoOwner, repoName, workflowName): Breadcrumb[] => [
                {
                    key: 'EngineeringAnalytics',
                    name: 'CI analytics',
                    path: urls.engineeringAnalytics(),
                    iconType: 'health',
                },
                {
                    key: 'EngineeringAnalyticsWorkflowsTab',
                    name: 'Workflows',
                    path: urls.engineeringAnalyticsWorkflows(),
                    iconType: 'health',
                },
                {
                    key: ['EngineeringAnalyticsWorkflowRuns', `${repoOwner}/${repoName}/${workflowName}`],
                    name: `${repoOwner}/${repoName} · ${workflowName}`,
                    iconType: 'health',
                },
            ],
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadRuns()
        actions.loadRunnerCosts()
    }),
])
