import { useQuery } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'

import { NotSignedInError } from '@/api/client'
import { chatKeys, listConversations } from '@/api/conversations'
import { isMissingFeature, retryUnlessMissing } from '@/api/reports'
import { listMySessions } from '@/api/tasks'
import { useAuthStore } from '@/auth/authStore'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { useDemoChatsQuery } from '@/demo/hooks'
import { toError } from '@/lib/errors'
import { chatListFromSources } from '@/model/adapters/chats'
import { errorQuery, loadingQuery } from '@/model/queryStates'
import type { ChatListItem, QueryState } from '@/model/types'

const CHAT_LIST_STALE_MS = 30_000

export interface ChatListQuery extends QueryState<ChatListItem[]> {
    /** One source loaded and the other failed. The list shows what loaded plus a retry line. */
    partialError: boolean
}

function useLiveChatList(enabled: boolean): ChatListQuery {
    const scope = useProjectScope()
    const userId = useAuthStore((state) => state.user?.id)
    const active = enabled && scope !== null
    // A session restored from before the app stored the numeric id has none until the account reloads.
    const sessionsEnabled = active && typeof userId === 'number'
    const [pulling, setPulling] = useState(false)

    const conversations = useQuery({
        queryKey: chatKeys.conversations(scope),
        queryFn: ({ signal }) => listConversations(signal),
        enabled: active,
        retry: retryUnlessMissing,
        staleTime: CHAT_LIST_STALE_MS,
    })
    const sessions = useQuery({
        queryKey: chatKeys.sessions(scope, userId),
        queryFn: ({ signal }) => (typeof userId === 'number' ? listMySessions(userId, signal) : Promise.resolve([])),
        enabled: sessionsEnabled,
        retry: retryUnlessMissing,
        staleTime: CHAT_LIST_STALE_MS,
    })

    const conversationsFailed = conversations.isError && conversations.data === undefined
    const sessionsErrored = sessionsEnabled && sessions.isError && sessions.data === undefined
    // A 403 or 404 from tasks means this user has no sandbox sessions to show, not a load that a retry can fix.
    const sessionsUnavailable = sessionsErrored && isMissingFeature(sessions.error)
    const sessionsFailed = sessionsErrored && !sessionsUnavailable
    const conversationsSettled = conversations.data !== undefined || conversationsFailed
    const sessionsSettled = !sessionsEnabled || sessions.data !== undefined || sessionsErrored
    const sessionData = sessionsEnabled ? sessions.data : undefined

    const items = useMemo(
        () => chatListFromSources({ conversations: conversations.data, sessions: sessionData, scope }),
        [conversations.data, sessionData, scope]
    )

    const { refetch: refetchConversations } = conversations
    const { refetch: refetchSessions } = sessions
    const refetch = useCallback(async (): Promise<void> => {
        setPulling(true)
        try {
            await Promise.all([refetchConversations(), sessionsEnabled ? refetchSessions() : Promise.resolve()])
        } finally {
            setPulling(false)
        }
    }, [refetchConversations, refetchSessions, sessionsEnabled])

    if (!scope) {
        return { ...errorQuery(new NotSignedInError()), partialError: false }
    }
    if (conversationsFailed && (sessionsErrored || !sessionsEnabled)) {
        return { ...errorQuery(toError(conversations.error), refetch), partialError: false }
    }
    if (!conversationsSettled || !sessionsSettled) {
        return { ...loadingQuery<ChatListItem[]>(), refetch, partialError: false }
    }
    return {
        data: items,
        isLoading: false,
        isError: false,
        error: null,
        isRefetching: pulling,
        refetch,
        partialError: conversationsFailed || sessionsFailed,
    }
}

export function useChatList(): ChatListQuery {
    const mode = useDataMode()
    const demoQuery = useDemoChatsQuery()
    const liveQuery = useLiveChatList(mode === 'live')
    if (mode === 'loading') {
        return { ...loadingQuery<ChatListItem[]>(), partialError: false }
    }
    if (mode === 'demo') {
        return { ...demoQuery, partialError: false }
    }
    return liveQuery
}
