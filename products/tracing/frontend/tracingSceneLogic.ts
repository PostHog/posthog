import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { tracingDataLogic } from './tracingDataLogic'
import type { tracingSceneLogicType } from './tracingSceneLogicType'

export const tracingSceneLogic = kea<tracingSceneLogicType>([
    path(['products', 'tracing', 'frontend', 'tracingSceneLogic']),

    connect({
        values: [
            tracingDataLogic,
            ['spans', 'spansLoading', 'sparklineData', 'sparklineRowsLoading', 'traceSpans', 'traceSpansLoading'],
        ],
        actions: [tracingDataLogic, ['loadSpans', 'loadTraceSpans']],
    }),

    actions({
        openTraceModal: (traceId: string) => ({ traceId }),
        closeTraceModal: true,
    }),

    reducers({
        selectedTraceId: [
            null as string | null,
            {
                openTraceModal: (_, { traceId }) => traceId,
                closeTraceModal: () => null,
            },
        ],
    }),

    selectors({
        isTraceModalOpen: [
            (s) => [s.selectedTraceId],
            (selectedTraceId: string | null): boolean => selectedTraceId !== null,
        ],
    }),

    listeners(({ actions }) => ({
        openTraceModal: ({ traceId }) => {
            actions.loadTraceSpans(traceId)
        },
    })),
])
