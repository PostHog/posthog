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
        loadEventsForHighlight: (entryId: string, programId: string, uuids: string[]) => ({
            entryId,
            programId,
            uuids,
        }),
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
        highlightedEvents: [
            {} as Record<string, ProgramEventApi[]>,
            {
                loadEventsForHighlight: async ({
                    entryId,
                    programId,
                    uuids,
                }: {
                    entryId: string
                    programId: string
                    uuids: string[]
                }): Promise<Record<string, ProgramEventApi[]>> => {
                    const response = await liveDebuggerSessionsProgramEventsRetrieve(
                        String(values.currentProjectId),
                        props.id,
                        { program_id: programId, limit: 1000 }
                    )
                    const set = new Set(uuids)
                    return {
                        ...values.highlightedEvents,
                        [entryId]: (response.results ?? []).filter((e) => set.has(e.id)),
                    }
                },
            },
        ],
    })),

    listeners(({ actions, props, values }) => ({
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
