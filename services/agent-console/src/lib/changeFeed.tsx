/**
 * The change-feed bridge — the wire between the server's "something changed"
 * stream and the console's keyed reads.
 *
 * One team-scoped SSE, opened once at the app root. Each `{type, team_id,
 * id}` event becomes keyed invalidations (the collection key + the item
 * key), debounced so a burst of changes is one refetch per key. Any read
 * keyed to that entity (`useResource(..., { key: changeKey(type, teamId) })`)
 * re-derives from truth. Nothing else has to know the feed exists.
 *
 * Served by the agent-ingress (the streaming tier) via the same
 * `/api/agents/v1/...` proxy the dock's session SSE uses; the proxy attaches
 * the OAuth bearer (EventSource can't set headers).
 */

'use client'

import { useEffect } from 'react'

import { bumpReload, invalidate } from './reloadSignal'

/**
 * Query-key convention. `[type]:[teamId]` addresses a collection (a team's
 * agent list); `[type]:[teamId]:[id]` addresses one item (an agent detail
 * page). Reads key themselves with this; the feed invalidates with this.
 */
export function changeKey(type: string, teamId: number | string, id?: string): string {
    return id ? `${type}:${teamId}:${id}` : `${type}:${teamId}`
}

interface ChangeEvent {
    type?: string
    team_id?: number
    id?: string
}

function useChangeFeed(teamId: number | null): void {
    useEffect(() => {
        if (teamId == null || typeof window === 'undefined') {
            return
        }
        const url = `/api/agents/v1/teams/${teamId}/agent-changes`
        let es: EventSource | null = null
        let closed = false
        let hasConnected = false
        let retry: ReturnType<typeof setTimeout> | undefined

        // Coalesce a burst of events into one invalidation per key.
        const pending = new Set<string>()
        let flushTimer: ReturnType<typeof setTimeout> | undefined
        const flush = (): void => {
            flushTimer = undefined
            for (const key of pending) {
                invalidate(key)
            }
            pending.clear()
        }
        const enqueue = (key: string): void => {
            pending.add(key)
            if (!flushTimer) {
                flushTimer = setTimeout(flush, 60)
            }
        }

        const open = (): void => {
            if (closed) {
                return
            }
            es = new EventSource(url, { withCredentials: true })
            es.onopen = (): void => {
                // Redis pub/sub has no replay — events published during a
                // disconnect are lost. On a *re*connect, force every keyed
                // read to re-sync so nothing stays stale. (First connect:
                // the reads just loaded, so skip.)
                if (hasConnected) {
                    bumpReload()
                }
                hasConnected = true
            }
            es.onmessage = (e): void => {
                let ev: ChangeEvent
                try {
                    ev = JSON.parse(e.data)
                } catch {
                    return
                }
                if (!ev.type || ev.team_id == null) {
                    return
                }
                enqueue(changeKey(ev.type, ev.team_id))
                if (ev.id) {
                    enqueue(changeKey(ev.type, ev.team_id, ev.id))
                }
            }
            es.onerror = (): void => {
                es?.close()
                es = null
                if (!closed) {
                    retry = setTimeout(open, 3000)
                }
            }
        }
        open()

        return () => {
            closed = true
            if (retry) {
                clearTimeout(retry)
            }
            if (flushTimer) {
                clearTimeout(flushTimer)
            }
            es?.close()
        }
    }, [teamId])
}

/**
 * Mount once at the app root (inside the session context). Opens the team
 * change feed and routes events to keyed invalidations for the whole app.
 */
export function ChangeFeedProvider({
    teamId,
    children,
}: {
    teamId: number | null
    children: React.ReactNode
}): React.ReactElement {
    useChangeFeed(teamId)
    return <>{children}</>
}
