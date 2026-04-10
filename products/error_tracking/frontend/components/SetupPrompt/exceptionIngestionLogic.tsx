import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiRequest } from 'lib/api'

import type { exceptionIngestionLogicType } from './exceptionIngestionLogicType'

export const exceptionIngestionLogic = kea<exceptionIngestionLogicType>([
    path(['products', 'error_tracking', 'components', 'SetupPrompt', 'exceptionIngestionLogic']),
    loaders({
        hasSentExceptionEvent: {
            __default: undefined as boolean | undefined,
            loadExceptionIngestionState: async (): Promise<boolean> => {
                const issues = await new ApiRequest()
                    .errorTrackingIssues()
                    .withQueryString({ limit: 1 })
                    .get()
                    .catch(() => null)

                return Array.isArray(issues?.results) && issues.results.length > 0
            },
        },
    }),

    afterMount(({ actions }) => {
        actions.loadExceptionIngestionState()
    }),
])
