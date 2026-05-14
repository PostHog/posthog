import { actions, afterMount, connect, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { liveDebuggerSessionsCreate, liveDebuggerSessionsList } from 'products/live_debugger/frontend/generated/api'
import type { LiveDebuggerSessionListItemApi } from 'products/live_debugger/frontend/generated/api.schemas'

import type { debuggingSessionsLogicType } from './debuggingSessionsLogicType'

export const debuggingSessionsLogic = kea<debuggingSessionsLogicType>([
    path(['products', 'live_debugger', 'debuggingSessionsLogic']),

    connect(() => ({ values: [teamLogic, ['currentProjectId']] })),

    actions({
        startSession: (title: string, description: string) => ({ title, description }),
    }),

    loaders(({ values }) => ({
        sessions: [
            [] as LiveDebuggerSessionListItemApi[],
            {
                loadSessions: async (): Promise<LiveDebuggerSessionListItemApi[]> => {
                    const response = await liveDebuggerSessionsList(String(values.currentProjectId))
                    return response.results ?? []
                },
                createSession: async ({
                    title,
                    description,
                }: {
                    title: string
                    description: string
                }): Promise<LiveDebuggerSessionListItemApi[]> => {
                    const created = await liveDebuggerSessionsCreate(String(values.currentProjectId), {
                        title,
                        description,
                    })
                    // Project the full session onto the list-item shape; entries are not needed here.
                    const item: LiveDebuggerSessionListItemApi = {
                        id: created.id,
                        title: created.title,
                        description: created.description ?? '',
                        status: created.status,
                        created_at: created.created_at,
                        closed_at: created.closed_at,
                    }
                    return [item, ...values.sessions]
                },
            },
        ],
    })),

    reducers({}),

    afterMount(({ actions }) => {
        actions.loadSessions()
    }),
])
