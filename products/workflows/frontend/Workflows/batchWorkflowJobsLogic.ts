import { afterMount, kea, key, path, props, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import type { batchWorkflowJobsLogicType } from './batchWorkflowJobsLogicType'
import { type HogFlowAction, HogFlowBatchJob } from './hogflows/types'

export interface WorkflowLogicProps {
    id?: string
}

export type TriggerAction = Extract<HogFlowAction, { type: 'trigger' }>

export const batchWorkflowJobsLogic = kea<batchWorkflowJobsLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'batchWorkflowJobsLogic']),
    props({ id: 'new' } as WorkflowLogicProps),
    key((props) => props.id || 'new'),
    lazyLoaders(({ props }) => ({
        batchWorkflowJobs: [
            null as HogFlowBatchJob[] | null,
            {
                loadBatchWorkflowJobs: async () => {
                    if (!props.id || props.id === 'new') {
                        return null
                    }

                    return api.hogFlows.getHogFlowBatchJobs(props.id)
                },
            },
        ],
    })),
    selectors({
        pastJobs: [
            (s) => [s.batchWorkflowJobs],
            (batchWorkflowJobs) =>
                (batchWorkflowJobs || []).filter(
                    (job) => !job.scheduled_at || dayjs(job.scheduled_at).isBefore(dayjs())
                ),
        ],
        futureJobs: [
            (s) => [s.batchWorkflowJobs],
            (batchWorkflowJobs) =>
                (batchWorkflowJobs || []).filter((job) => job.scheduled_at && dayjs(job.scheduled_at).isAfter(dayjs())),
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadBatchWorkflowJobs()
    }),
])
