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
                const response = await new ApiRequest()
                    .errorTrackingIssuesExists()
                    .get()
                    .catch(() => null)

                return response?.exists === true
            },
        },
    }),

    afterMount(({ actions }) => {
        actions.loadExceptionIngestionState()
    }),
])
