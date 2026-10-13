import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { NotSignedInError } from '@/api/client'
import { isMissingFeature, type ProjectScope, retryUnlessMissing, scopeKey } from '@/api/reports'
import { listMySessions } from '@/api/tasks'
import { useAuthStore } from '@/auth/authStore'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { useDemoChatsQuery } from '@/demo/hooks'
import { toError } from '@/lib/errors'
import { chatListFromSessions } from '@/model/adapters/chats'
import { errorQuery, loadingQuery, successQuery } from '@/model/queryStates'
import type { ChatListItem, QueryState } from '@/model/types'

const CHAT_LIST_STALE_MS = 30_000

/** Query keys for the chats list. Every key carries the host and project so a project switch never shows stale data. */
export const sessionListKeys = {
    all: (scope: ProjectScope | null) => ['chat-sessions', ...scopeKey(scope)] as const,
    mine: (scope: ProjectScope | null, userId: number | undefined) =>
        [...sessionListKeys.all(scope), userId ?? null] as const,
}

function useLiveChatList(enabled: boolean): QueryState<ChatListItem[]> {
    const scope = useProjectScope()
    const userId = useAuthStore((state) => state.user?.id)
    const accountLoading = useAuthStore((state) => state.accountLoading)
    const accountError = useAuthStore((state) => state.accountError)
    const reloadAccount = useAuthStore((state) => state.reloadAccount)
    // A session restored from before the app stored the numeric id has none until the account reloads.
    const missingUserId = enabled && scope !== null && typeof userId !== 'number'
    const active = enabled && scope !== null && typeof userId === 'number'
    const [pulling, setPulling] = useState(false)
    const [accountChecked, setAccountChecked] = useState(false)

    useEffect(() => {
        if (!missingUserId || accountChecked) {
            return undefined
        }
        let current = true
        reloadAccount().finally(() => {
            if (current) {
                setAccountChecked(true)
            }
        })
        return () => {
            current = false
        }
    }, [missingUserId, accountChecked, reloadAccount])

    const sessions = useQuery({
        queryKey: sessionListKeys.mine(scope, userId),
        queryFn: ({ signal }) => (typeof userId === 'number' ? listMySessions(userId, signal) : Promise.resolve([])),
        enabled: active,
        retry: retryUnlessMissing,
        staleTime: CHAT_LIST_STALE_MS,
    })

    const failed = sessions.isError && sessions.data === undefined
    // A 403 or 404 from tasks means this user has no sandbox sessions to show, not a load that a retry can fix.
    const unavailable = failed && isMissingFeature(sessions.error)

    const items = useMemo(
        () => (unavailable ? [] : chatListFromSessions(sessions.data, scope)),
        [unavailable, sessions.data, scope]
    )

    const { refetch: refetchSessions } = sessions
    const refetch = useCallback(async (): Promise<void> => {
        setPulling(true)
        try {
            await refetchSessions()
        } finally {
            setPulling(false)
        }
    }, [refetchSessions])

    if (!scope) {
        return errorQuery(new NotSignedInError())
    }
    if (missingUserId) {
        if (!accountChecked || accountLoading) {
            return { ...loadingQuery<ChatListItem[]>(), refetch: reloadAccount }
        }
        if (accountError) {
            return errorQuery(new Error(accountError), reloadAccount)
        }
        return successQuery<ChatListItem[]>([], { refetch: reloadAccount })
    }
    if (failed && !unavailable) {
        return errorQuery(toError(sessions.error), refetch)
    }
    if (sessions.data === undefined && !unavailable) {
        return { ...loadingQuery<ChatListItem[]>(), refetch }
    }
    return {
        data: items,
        isLoading: false,
        isError: false,
        error: null,
        isRefetching: pulling,
        refetch,
    }
}

export function useChatList(): QueryState<ChatListItem[]> {
    const mode = useDataMode()
    const demoQuery = useDemoChatsQuery()
    const liveQuery = useLiveChatList(mode === 'live')
    if (mode === 'loading') {
        return loadingQuery<ChatListItem[]>()
    }
    if (mode === 'demo') {
        return demoQuery
    }
    return liveQuery
}
