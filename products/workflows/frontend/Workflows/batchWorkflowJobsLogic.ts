import { kea, key, path, props, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
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
        jobs: [(s) => [s.batchWorkflowJobs], (batchWorkflowJobs) => batchWorkflowJobs || []],
    }),
    urlToAction(({ props, actions }) => ({
        [urls.workflow(props.id || 'new', 'logs')]: () => {
            actions.loadBatchWorkflowJobs()
        },
        [urls.workflow(props.id || 'new', 'metrics')]: () => {
            actions.loadBatchWorkflowJobs()
        },
    })),
])
