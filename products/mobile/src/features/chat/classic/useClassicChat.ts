import { useQueryClient } from '@tanstack/react-query'
import { randomUUID } from 'expo-crypto'
import { useCallback, useEffect, useRef, useState } from 'react'
import { AppState } from 'react-native'

import { ApiError } from '@/api/client'
import { cancelConversation, getConversation, streamConversation } from '@/api/conversations'
import { readSse } from '@/api/sse'
import { requestWithDeadline } from '@/api/transport'
import { useProjectScope } from '@/auth/useProjectScope'
import { currentAiIdentity, useAiApproval } from '@/features/ai/aiApproval'
import { conversationListKeys } from '@/features/chats/conversationKeys'
import { sessionListKeys } from '@/features/chats/hooks'
import { sleep } from '@/lib/sleep'

import { toChatError } from '../chatErrors'
import {
    appendClassicMessage,
    type ClassicForm,
    classicHistory,
    EMPTY_CLASSIC_STATE,
    reduceClassicEvent,
} from './classicMessages'

const RECOVERY_ATTEMPTS = 2
const RECOVERY_DELAY_MS = 1000

async function retryRecovery(work: () => Promise<void>, signal: AbortSignal, active: () => boolean): Promise<void> {
    for (let attempt = 0; attempt < RECOVERY_ATTEMPTS && active(); attempt++) {
        try {
            await work()
            return
        } catch (failure) {
            if (!active()) return
            if (
                attempt === RECOVERY_ATTEMPTS - 1 ||
                (failure instanceof ApiError && [401, 403, 404].includes(failure.status))
            )
                throw failure
            await sleep(RECOVERY_DELAY_MS, signal)
        }
    }
}

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
    const unacceptedConversation = useRef<string | null>(null)
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
    const appState = useRef(AppState.currentState)
    const confirmConversation = useCallback((conversation: string): void => {
        if (unacceptedConversation.current === conversation) unacceptedConversation.current = null
    }, [])
    const canConnect = useCallback(
        (): boolean =>
            mounted.current &&
            !approval.signal.aborted &&
            currentAiIdentity() === openedIdentity.current &&
            (appState.current === null || appState.current === 'active'),
        [approval.signal]
    )

    const recoverConversation = useCallback(
        async (conversation: string, signal: AbortSignal, generation: number): Promise<void> => {
            const active = (): boolean => generation === epoch.current && !signal.aborted && canConnect()
            const publish = (saved: Awaited<ReturnType<typeof getConversation>>): ReturnType<typeof classicHistory> => {
                const history = classicHistory(saved.messages, saved.title, saved.pending_approvals)
                confirmConversation(conversation)
                setId(conversation)
                setState((previous) => {
                    const merged =
                        saved.status === 'in_progress' ? saved.messages.reduce(appendClassicMessage, previous) : history
                    return {
                        ...history,
                        messages: merged.messages,
                        nextMessageId: merged.nextMessageId,
                        error: previous.error,
                    }
                })
                return history
            }
            await retryRecovery(
                async () => {
                    const saved = await getConversation(conversation, signal)
                    if (!active()) return
                    const history = publish(saved)
                    if (
                        saved.status !== 'in_progress' ||
                        saved.pending_approvals.some((approval) => approval.decision_status === 'pending') ||
                        history.form
                    )
                        return
                    if (!(await approval.request()) || !active()) return
                    setWorking(true)
                    setLoading(false)
                    const response = await requestWithDeadline(
                        (signal) =>
                            streamConversation(
                                { conversation, content: null, trace_id: randomUUID(), is_sandbox: false },
                                signal
                            ),
                        signal
                    )
                    if (!active()) return
                    await readSse(
                        response,
                        (event) => {
                            if (active()) setState((previous) => reduceClassicEvent(previous, event))
                        },
                        signal,
                        60_000
                    )
                    const completed = await getConversation(conversation, signal)
                    if (active()) publish(completed)
                },
                signal,
                active
            )
        },
        [approval.request, canConnect, confirmConversation]
    )

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
            const active = (): boolean => generation === epoch.current && canConnect()
            if (busy.current || !active()) return false
            busy.current = true
            setWorking(true)
            const conversation = idRef.current ?? randomUUID()
            const traceId = randomUUID()
            const abort = new AbortController()
            let accepted = false
            try {
                if (!(await approval.request()) || !active()) return false
                if (!idRef.current) unacceptedConversation.current = conversation
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
                confirmConversation(conversation)
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
                    if (accepted || (content === null && !resumePayload)) {
                        try {
                            await recoverConversation(conversation, abort.signal, generation)
                            if (active()) setHistoryError(null)
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
        [client, scope, approval.request, canConnect, confirmConversation, recoverConversation]
    )

    const resetUnacceptedConversation = useCallback((conversation: string, failure: unknown): boolean => {
        if (!(failure instanceof ApiError) || failure.status !== 404 || unacceptedConversation.current !== conversation)
            return false
        unacceptedConversation.current = null
        idRef.current = null
        setId(null)
        setState(EMPTY_CLASSIC_STATE)
        return true
    }, [])

    const reload = useCallback(async (): Promise<void> => {
        const conversation = idRef.current
        if (!conversation || busy.current || reloadBusy.current || !canConnect()) return
        reloadBusy.current = true
        busy.current = true
        const generation = epoch.current
        const abort = new AbortController()
        controller.current = abort
        setLoading(true)
        setHistoryError(null)
        setError(null)
        try {
            await recoverConversation(conversation, abort.signal, generation)
        } catch (failure) {
            if (
                generation === epoch.current &&
                !abort.signal.aborted &&
                !resetUnacceptedConversation(conversation, failure)
            )
                setHistoryError(toChatError(failure).message)
        } finally {
            if (generation === epoch.current) {
                reloadBusy.current = false
                busy.current = false
                controller.current = null
                setLoading(false)
                setWorking(false)
            }
        }
    }, [recoverConversation, canConnect, resetUnacceptedConversation])

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
        unacceptedConversation.current = null
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

    useEffect(() => {
        const subscription = AppState.addEventListener('change', (next) => {
            const previous = appState.current
            appState.current = next
            if (next === previous) return
            // Detach the transport only; the server keeps generating until an explicit cancellation.
            invalidate()
            setWorking(false)
            setStopping(false)
            setLoading(false)
            if (next === 'active') void reload()
        })
        return () => subscription.remove()
    }, [invalidate, reload])

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
