import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { mindmapPostitsBulkPositionCreate, mindmapStateRetrieve } from 'products/mindmap/frontend/generated/api'
import type { MindMapPostItApi, _MindMapStateApi } from 'products/mindmap/frontend/generated/api.schemas'

import type { mindmapLogicType } from './mindmapLogicType'

const POLL_INTERVAL_MS = 5000
const DRAG_DEBOUNCE_MS = 500

export interface MindMapEdgeDTO {
    source: string
    target: string
}

export interface PendingDrag {
    position_x: number
    position_y: number
}

export const mindmapLogic = kea<mindmapLogicType>([
    path(['products', 'mindmap', 'frontend', 'mindmapLogic']),
    actions({
        startPolling: true,
        stopPolling: true,
        nodeDragged: (shortId: string, x: number, y: number) => ({ shortId, x, y }),
        flushPendingDrags: true,
        clearPendingDrags: (shortIds: string[]) => ({ shortIds }),
    }),
    loaders(({ values }) => ({
        state: [
            null as _MindMapStateApi | null,
            {
                loadState: async (_: void, breakpoint) => {
                    const headers: Record<string, string> = {}
                    if (values.version) {
                        headers['If-None-Match'] = `"${values.version}"`
                    }
                    const projectId = String(teamLogic.values.currentProjectId)
                    try {
                        const result = await mindmapStateRetrieve(projectId, { headers })
                        breakpoint()
                        return result
                    } catch (e: any) {
                        if (e?.status === 304) {
                            return values.state
                        }
                        throw e
                    }
                },
            },
        ],
    })),
    reducers({
        pendingDrags: [
            {} as Record<string, PendingDrag>,
            {
                nodeDragged: (state, { shortId, x, y }) => ({
                    ...state,
                    [shortId]: { position_x: x, position_y: y },
                }),
                clearPendingDrags: (state, { shortIds }) => {
                    const next = { ...state }
                    shortIds.forEach((id) => delete next[id])
                    return next
                },
            },
        ],
    }),
    selectors({
        version: [(s) => [s.state], (state): string | null => state?.version ?? null],
        postits: [
            (s) => [s.state, s.pendingDrags],
            (state, pendingDrags): MindMapPostItApi[] => {
                const list = state?.postits ?? []
                return list.map((p) => {
                    const pending = pendingDrags[p.short_id]
                    return pending ? { ...p, position_x: pending.position_x, position_y: pending.position_y } : p
                })
            },
        ],
        edges: [(s) => [s.state], (state): MindMapEdgeDTO[] => state?.edges ?? []],
    }),
    listeners(({ actions, values, cache }) => ({
        startPolling: () => {
            if (cache.pollHandle) {
                return
            }
            actions.loadState()
            cache.pollHandle = window.setInterval(() => {
                if (document.visibilityState === 'visible') {
                    actions.loadState()
                }
            }, POLL_INTERVAL_MS)
        },
        stopPolling: () => {
            if (cache.pollHandle) {
                window.clearInterval(cache.pollHandle)
                cache.pollHandle = null
            }
        },
        nodeDragged: () => {
            if (cache.dragFlushHandle) {
                window.clearTimeout(cache.dragFlushHandle)
            }
            cache.dragFlushHandle = window.setTimeout(() => {
                actions.flushPendingDrags()
            }, DRAG_DEBOUNCE_MS)
        },
        flushPendingDrags: async () => {
            const drags = values.pendingDrags
            const shortIds = Object.keys(drags)
            if (!shortIds.length) {
                return
            }
            const updates = shortIds.map((short_id) => ({
                short_id,
                position_x: drags[short_id].position_x,
                position_y: drags[short_id].position_y,
            }))
            const projectId = String(teamLogic.values.currentProjectId)
            try {
                await mindmapPostitsBulkPositionCreate(projectId, { updates })
                actions.clearPendingDrags(shortIds)
            } catch {
                // On failure, drop the optimistic drag so the next poll restores server truth.
                actions.clearPendingDrags(shortIds)
                actions.loadState()
            }
        },
    })),
])
