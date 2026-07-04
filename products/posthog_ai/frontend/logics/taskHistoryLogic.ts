import { actions, connect, events, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { loadErrorMessage } from '../lib/load-error'
import { OriginProduct, Task } from '../types/taskTypes'
import type { taskHistoryLogicType } from './taskHistoryLogicType'

// Deliberately independent of `tasksLogic` — the panel history must show the user's own recent
// posthog_ai tasks regardless of whatever search/assignee filter is active on the /tasks scene.
export const taskHistoryLogic = kea<taskHistoryLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'taskHistoryLogic']),

    connect(() => ({
        values: [userLogic, ['user']],
    })),

    actions({
        taskArchived: (taskId: string) => ({ taskId }),
    }),

    loaders(({ values }) => ({
        history: [
            [] as Task[],
            {
                loadHistory: async (_: void, breakpoint) => {
                    const response = await api.tasks.list({
                        origin_product: OriginProduct.POSTHOG_AI,
                        created_by: values.user?.id,
                        limit: 20,
                    })
                    breakpoint()
                    return response.results
                },
            },
        ],
    })),

    reducers({
        history: {
            // The full-list surface archives via `tasksLogic.deleteTask` and dispatches this to keep
            // this independent list in sync without re-fetching.
            taskArchived: (state, { taskId }) => state.filter((task) => task.id !== taskId),
        },
        historyError: [
            null as string | null,
            {
                loadHistory: () => null,
                loadHistoryFailure: (_, { error, errorObject }) => loadErrorMessage(error, errorObject),
            },
        ],
    }),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadHistory()
        },
    })),
])
