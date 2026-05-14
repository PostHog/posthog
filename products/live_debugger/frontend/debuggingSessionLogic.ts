import { actions, afterMount, connect, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import {
    liveDebuggerSessionsCloseCreate,
    liveDebuggerSessionsProgramEventsRetrieve,
    liveDebuggerSessionsRetrieve,
} from 'products/live_debugger/frontend/generated/api'
import type { LiveDebuggerSessionApi, ProgramEventApi } from 'products/live_debugger/frontend/generated/api.schemas'

import type { debuggingSessionLogicType } from './debuggingSessionLogicType'

export interface SessionLogicProps {
    id: string
}

export const debuggingSessionLogic = kea<debuggingSessionLogicType>([
    props({} as SessionLogicProps),
    key((p) => p.id),
    path((k) => ['products', 'live_debugger', 'debuggingSessionLogic', k]),

    connect(() => ({ values: [teamLogic, ['currentProjectId']] })),

    actions({
        closeSession: (conclusionMarkdown: string | null) => ({ conclusionMarkdown }),
    }),

    loaders(({ props, values }) => ({
        session: [
            null as LiveDebuggerSessionApi | null,
            {
                loadSession: async (): Promise<LiveDebuggerSessionApi> => {
                    return await liveDebuggerSessionsRetrieve(String(values.currentProjectId), props.id)
                },
            },
        ],
        // Flat map of event UUID -> probe event, populated by fetching program_events for every
        // program in the session. The notebook's EventHighlightEntry uses this to render highlighted
        // event payloads inline. Refreshes after every session reload.
        eventsByUuid: [
            {} as Record<string, ProgramEventApi>,
            {
                loadAllEvents: async (): Promise<Record<string, ProgramEventApi>> => {
                    const programs = values.session?.programs ?? []
                    if (programs.length === 0) {
                        return {}
                    }
                    const projectId = String(values.currentProjectId)
                    const responses = await Promise.all(
                        programs.map((p) =>
                            liveDebuggerSessionsProgramEventsRetrieve(projectId, props.id, {
                                program_id: p.id,
                                limit: 1000,
                            }).catch(() => ({ results: [] as ProgramEventApi[] }))
                        )
                    )
                    const map: Record<string, ProgramEventApi> = {}
                    for (const response of responses) {
                        for (const event of response.results ?? []) {
                            map[event.id] = event
                        }
                    }
                    return map
                },
            },
        ],
    })),

    listeners(({ actions, props, values }) => ({
        loadSessionSuccess: () => {
            actions.loadAllEvents()
        },
        closeSession: async ({ conclusionMarkdown }) => {
            await liveDebuggerSessionsCloseCreate(String(values.currentProjectId), props.id, {
                conclusion_markdown: conclusionMarkdown ?? undefined,
            })
            actions.loadSession()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadSession()
    }),
])
