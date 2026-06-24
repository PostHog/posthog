import { afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { engineeringAnalyticsWorkflowRun } from '../generated/api'
import type { WorkflowRunDetailApi } from '../generated/api.schemas'
import type { workflowRunDetailLogicType } from './workflowRunDetailLogicType'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export interface WorkflowRunDetailLogicProps {
    repoOwner: string
    repoName: string
    runId: number
    // Which GitHub source the list was scoped to, threaded from `?source=` via paramsToProps.
    sourceId: string | null
    tabId?: string
}

export const workflowRunDetailLogic = kea<workflowRunDetailLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'workflowRunDetailLogic']),
    props({} as WorkflowRunDetailLogicProps),
    // sourceId is part of the identity: the same run id only exists within one source.
    key(
        (props) =>
            `${props.tabId ?? 'default'}/${props.repoOwner}/${props.repoName}/runs/${props.runId}@${props.sourceId ?? ''}`
    ),

    loaders(({ props }) => ({
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
        breadcrumbs: [
            (_, p) => [p.repoOwner, p.repoName, p.runId],
            (repoOwner, repoName, runId): Breadcrumb[] => [
                {
                    key: 'EngineeringAnalytics',
                    name: 'CI analytics',
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

    afterMount(({ actions }) => {
        actions.loadRun()
    }),
])
