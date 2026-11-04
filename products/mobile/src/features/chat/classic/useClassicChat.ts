import { useQueryClient } from '@tanstack/react-query'
import { randomUUID } from 'expo-crypto'
import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '@/api/client'
import { cancelConversation, getConversation, streamConversation } from '@/api/conversations'
import { readSse } from '@/api/sse'
import { useProjectScope } from '@/auth/useProjectScope'
import { conversationListKeys } from '@/features/chats/conversationKeys'
import { sessionListKeys } from '@/features/chats/hooks'

import { toChatError } from '../chatErrors'
import { appendClassicMessage, classicHistory, EMPTY_CLASSIC_STATE, reduceClassicEvent } from './classicMessages'

export function useClassicChat(initialId?: string): {
    id: string | null
    state: typeof EMPTY_CLASSIC_STATE
    loading: boolean
    historyError: string | null
    working: boolean
    stopping: boolean
    error: string | null
    send: (text: string) => Promise<boolean>
    answer: (approved: boolean) => Promise<boolean>
    stop: () => Promise<void>
    reload: () => Promise<void>
    reset: () => void
    dismissError: () => void
} {
    const scope = useProjectScope()
    const client = useQueryClient()
    const [id, setId] = useState<string | null>(initialId ?? null)
    const idRef = useRef(id)
    const [state, setState] = useState(EMPTY_CLASSIC_STATE)
    const [loading, setLoading] = useState(!!initialId)
    const [historyError, setHistoryError] = useState<string | null>(null)
    const [working, setWorking] = useState(false)
    const [stopping, setStopping] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const busy = useRef(false)
    const stopBusy = useRef(false)
    const reloadBusy = useRef(false)
    const epoch = useRef(0)
    const controller = useRef<AbortController | null>(null)

    const stream = useCallback(
        async (content: string | null, proposal?: { id: string; approved: boolean }): Promise<boolean> => {
            if (busy.current) return false
            busy.current = true
            const generation = epoch.current
            const active = (): boolean => generation === epoch.current
            const conversation = idRef.current ?? randomUUID()
            idRef.current = conversation
            const traceId = randomUUID()
            const abort = new AbortController()
            controller.current = abort
            setWorking(true)
            setError(null)
            setState((previous) => {
                const next = { ...previous, error: null }
                return content ? appendClassicMessage(next, { type: 'human', content, trace_id: traceId }) : next
            })
            let accepted = false
            try {
                const response = await streamConversation(
                    {
                        conversation,
                        content,
                        trace_id: traceId,
                        is_sandbox: false,
                        ...(proposal
                            ? {
                                  resume_payload: {
                                      proposal_id: proposal.id,
                                      action: proposal.approved ? 'approve' : 'reject',
                                  },
                              }
                            : {}),
                    },
                    abort.signal
                )
                accepted = true
                if (!active()) return true
                idRef.current = conversation
                setId(conversation)
                if (proposal) setState((previous) => ({ ...previous, approval: null }))
                await readSse(
                    response,
                    (event) => {
                        if (active()) setState((previous) => reduceClassicEvent(previous, event))
                    },
                    abort.signal
                )
                if (active()) {
                    const saved = await getConversation(conversation, abort.signal)
                    if (active()) setState(classicHistory(saved.messages, saved.title, saved.pending_approvals))
                }
                return true
            } catch (failure) {
                if (active() && !abort.signal.aborted) {
                    if (accepted) {
                        setHistoryError('The reply was interrupted. Reconnect to load the latest messages.')
                    } else {
                        setError(toChatError(failure).message)
                    }
                    if (!accepted && content) {
                        setState((previous) => ({
                            ...previous,
                            messages: previous.messages.filter((message) => message.data.trace_id !== traceId),
                        }))
                    }
                    if (failure instanceof ApiError && failure.status === 409) {
                        idRef.current = conversation
                        setId(conversation)
                        setHistoryError('PostHog AI is still answering. Reconnect to continue this chat.')
                    }
                }
                return accepted
            } finally {
                if (active()) {
                    busy.current = false
                    controller.current = null
                    setWorking(false)
                    setStopping(false)
                    if (scope) {
                        void client.invalidateQueries({ queryKey: sessionListKeys.all(scope) })
                        void client.invalidateQueries({ queryKey: conversationListKeys.all(scope) })
                    }
                }
            }
        },
        [client, scope]
    )

    const reload = useCallback(async (): Promise<void> => {
        const conversation = idRef.current
        if (!conversation || busy.current || reloadBusy.current) return
        reloadBusy.current = true
        const generation = epoch.current
        const abort = new AbortController()
        controller.current = abort
        setLoading(true)
        setHistoryError(null)
        setError(null)
        try {
            const saved = await getConversation(conversation, abort.signal)
            if (generation !== epoch.current) return
            setState(classicHistory(saved.messages, saved.title, saved.pending_approvals))
            if (saved.status === 'in_progress' && saved.pending_approvals.length === 0) void stream(null)
        } catch (failure) {
            if (generation === epoch.current && !abort.signal.aborted) setHistoryError(toChatError(failure).message)
        } finally {
            if (generation === epoch.current) {
                reloadBusy.current = false
                setLoading(false)
            }
        }
    }, [stream])

    useEffect(() => {
        if (initialId) void reload()
        return () => {
            epoch.current++
            controller.current?.abort()
        }
    }, [initialId, reload])

    const stop = async (): Promise<void> => {
        if (!idRef.current || stopBusy.current) return
        const generation = epoch.current
        stopBusy.current = true
        setStopping(true)
        try {
            await cancelConversation(idRef.current)
        } catch (failure) {
            if (generation === epoch.current) setError(toChatError(failure).message)
        } finally {
            if (generation === epoch.current) {
                stopBusy.current = false
                setStopping(false)
            }
        }
    }
    const reset = (): void => {
        epoch.current++
        controller.current?.abort()
        controller.current = null
        busy.current = false
        stopBusy.current = false
        reloadBusy.current = false
        idRef.current = null
        setId(null)
        setState(EMPTY_CLASSIC_STATE)
        setError(null)
        setLoading(false)
        setHistoryError(null)
        setWorking(false)
        setStopping(false)
    }
    return {
        id,
        state,
        loading,
        historyError,
        working,
        stopping,
        error: error ?? state.error,
        send: (text) => stream(text),
        answer: (approved) =>
            state.approval ? stream(null, { id: state.approval.id, approved }) : Promise.resolve(false),
        stop,
        reload,
        reset,
        dismissError: () => {
            setError(null)
            setState((previous) => ({ ...previous, error: null }))
        },
    }
}
