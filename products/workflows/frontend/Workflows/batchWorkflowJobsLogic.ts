import { kea, key, path, props, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import type { batchWorkflowJobsLogicType } from './batchWorkflowJobsLogicType'
import { HogFlowBatchJob } from './hogflows/types'

export interface BatchWorkflowJobsLogicProps {
    id?: string
}

export const batchWorkflowJobsLogic = kea<batchWorkflowJobsLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'batchWorkflowJobsLogic']),
    props({ id: 'new' } as BatchWorkflowJobsLogicProps),
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
    urlToAction(({ props, actions }) => ({
        [urls.workflow(props.id, 'logs')]: () => {
            actions.loadBatchWorkflowJobs()
        },
    })),
])
