import { useQueryClient } from '@tanstack/react-query'
import { randomUUID } from 'expo-crypto'
import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '@/api/client'
import { cancelConversation, getConversation, streamConversation } from '@/api/conversations'
import { readSse } from '@/api/sse'
import { requestWithDeadline } from '@/api/transport'
import { useProjectScope } from '@/auth/useProjectScope'
import { currentAiIdentity, useAiApproval } from '@/features/ai/aiApproval'
import { conversationListKeys } from '@/features/chats/conversationKeys'
import { sessionListKeys } from '@/features/chats/hooks'

import { toChatError } from '../chatErrors'
import {
    appendClassicMessage,
    type ClassicForm,
    classicHistory,
    EMPTY_CLASSIC_STATE,
    reduceClassicEvent,
} from './classicMessages'

export function useClassicChat(
    initialId?: string,
    initialConversation?: Awaited<ReturnType<typeof getConversation>>
): {
    id: string | null
    state: typeof EMPTY_CLASSIC_STATE
    loading: boolean
    historyError: string | null
    working: boolean
    stopping: boolean
    error: string | null
    send: (text: string, onAccepted?: () => Promise<void>) => Promise<boolean>
    answer: (approved: boolean) => Promise<boolean>
    form: ClassicForm | null
    submitForm: (answers: Record<string, string | string[]>) => Promise<boolean>
    dismissForm: () => Promise<boolean>
    stop: () => Promise<void>
    reload: () => Promise<void>
    reset: () => void
    dismissError: () => void
} {
    const scope = useProjectScope()
    const client = useQueryClient()
    const approval = useAiApproval('chat', initialId ?? 'new')
    const openedIdentity = useRef(currentAiIdentity())
    const initialSnapshot = useRef(initialConversation?.id === initialId ? initialConversation : undefined)
    const [id, setId] = useState<string | null>(initialId ?? null)
    const idRef = useRef(id)
    const [state, setState] = useState(() =>
        initialSnapshot.current
            ? classicHistory(
                  initialSnapshot.current.messages,
                  initialSnapshot.current.title,
                  initialSnapshot.current.pending_approvals
              )
            : EMPTY_CLASSIC_STATE
    )
    const [loading, setLoading] = useState(!!initialId && !initialSnapshot.current)
    const [historyError, setHistoryError] = useState<string | null>(null)
    const [working, setWorking] = useState(false)
    const [stopping, setStopping] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const busy = useRef(false)
    const stopBusy = useRef(false)
    const reloadBusy = useRef(false)
    const epoch = useRef(0)
    const mounted = useRef(true)
    const controller = useRef<AbortController | null>(null)

    const stream = useCallback(
        async (
            content: string | null,
            resumePayload?:
                | { proposal_id: string; action: 'approve' | 'reject' }
                | { action: 'form'; form_answers: Record<string, string | string[]> }
                | { action: 'dismiss_form' },
            onAccepted?: () => Promise<void>
        ): Promise<boolean> => {
            const generation = epoch.current
            const active = (): boolean =>
                mounted.current &&
                generation === epoch.current &&
                !approval.signal.aborted &&
                currentAiIdentity() === openedIdentity.current
            if (busy.current || !active()) return false
            busy.current = true
            setWorking(true)
            const conversation = idRef.current ?? randomUUID()
            const traceId = randomUUID()
            const abort = new AbortController()
            let accepted = false
            try {
                if (!(await approval.request()) || !active()) return false
                idRef.current = conversation
                controller.current = abort
                setError(null)
                setState((previous) => {
                    const next = { ...previous, error: null }
                    return content ? appendClassicMessage(next, { type: 'human', content, trace_id: traceId }) : next
                })
                const response = await requestWithDeadline(
                    (signal) =>
                        streamConversation(
                            {
                                conversation,
                                content,
                                trace_id: traceId,
                                is_sandbox: false,
                                ...(resumePayload ? { resume_payload: resumePayload } : {}),
                            },
                            signal
                        ),
                    abort.signal
                )
                accepted = true
                await onAccepted?.()
                if (!active()) return true
                idRef.current = conversation
                setId(conversation)
                if (resumePayload) setState((previous) => ({ ...previous, approval: null, form: null }))
                await readSse(
                    response,
                    (event) => {
                        if (active()) setState((previous) => reduceClassicEvent(previous, event))
                    },
                    abort.signal,
                    60_000
                )
                if (active()) {
                    const saved = await getConversation(conversation, abort.signal)
                    if (active())
                        setState((previous) => ({
                            ...classicHistory(saved.messages, saved.title, saved.pending_approvals),
                            error: previous.error,
                        }))
                }
                return true
            } catch (failure) {
                if (active() && !abort.signal.aborted) {
                    if (accepted) {
                        try {
                            const saved = await getConversation(conversation, abort.signal)
                            if (!active()) return true
                            const history = classicHistory(saved.messages, saved.title, saved.pending_approvals)
                            if (saved.status === 'idle' || history.approval || history.form) {
                                setState((previous) => ({ ...history, error: previous.error }))
                                setHistoryError(null)
                            } else {
                                setHistoryError('The reply was interrupted. Reconnect to load the latest messages.')
                            }
                        } catch {
                            if (active() && !abort.signal.aborted)
                                setHistoryError('The reply was interrupted. Reconnect to load the latest messages.')
                        }
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
        [client, scope, approval.request, approval.signal]
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
            const history = classicHistory(saved.messages, saved.title, saved.pending_approvals)
            setState(history)
            if (
                saved.status === 'in_progress' &&
                !saved.pending_approvals.some((approval) => approval.decision_status === 'pending') &&
                !history.form
            )
                void stream(null)
        } catch (failure) {
            if (generation === epoch.current && !abort.signal.aborted) setHistoryError(toChatError(failure).message)
        } finally {
            if (generation === epoch.current) {
                reloadBusy.current = false
                setLoading(false)
            }
        }
    }, [stream])

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
    const invalidate = useCallback((): void => {
        epoch.current++
        controller.current?.abort()
        controller.current = null
        busy.current = false
        stopBusy.current = false
        reloadBusy.current = false
    }, [])
    const reset = useCallback((): void => {
        invalidate()
        idRef.current = null
        setId(null)
        setState(EMPTY_CLASSIC_STATE)
        setError(null)
        setLoading(false)
        setHistoryError(null)
        setWorking(false)
        setStopping(false)
    }, [invalidate])

    useEffect(() => {
        mounted.current = true
        reset()
        idRef.current = initialId ?? null
        setId(initialId ?? null)
        const saved = initialSnapshot.current?.id === initialId ? initialSnapshot.current : undefined
        if (saved) {
            const history = classicHistory(saved.messages, saved.title, saved.pending_approvals)
            setState(history)
            if (
                saved.status === 'in_progress' &&
                !saved.pending_approvals.some((approval) => approval.decision_status === 'pending') &&
                !history.form
            )
                void stream(null)
        } else if (initialId) {
            void reload()
        }
        return () => {
            mounted.current = false
            invalidate()
        }
    }, [initialId, reload, reset, invalidate, stream])

    return {
        id,
        state,
        loading,
        historyError,
        working,
        stopping,
        error: error ?? state.error,
        send: (text, onAccepted) => stream(text, undefined, onAccepted),
        answer: (approved) =>
            state.approval
                ? stream(null, { proposal_id: state.approval.id, action: approved ? 'approve' : 'reject' })
                : Promise.resolve(false),
        form: state.form,
        submitForm: (answers) =>
            state.form ? stream(null, { action: 'form', form_answers: answers }) : Promise.resolve(false),
        dismissForm: () => (state.form ? stream(null, { action: 'dismiss_form' }) : Promise.resolve(false)),
        stop,
        reload,
        reset,
        dismissError: () => {
            setError(null)
            setState((previous) => ({ ...previous, error: null }))
        },
    }
}
