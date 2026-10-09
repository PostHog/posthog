import { randomUUID } from 'expo-crypto'
import { useCallback, useEffect, useReducer, useRef, useState } from 'react'

import { ApiError } from '@/api/client'
import {
    type ConversationEvent,
    fetchConversation,
    openConversationStream,
    readConversationStream,
} from '@/api/conversations'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { sleep } from '@/lib/sleep'

import { isNetworkError, toChatError } from './chatErrors'
import { chatPrompt } from './contextPrompt'
import { type ChatThreadAction, chatThreadReducer, initialChatThread } from './conversation'
import type { ChatContext, ChatEntry, ChatError } from './types'

const RECONNECT_STEP_MS = 1000
const MAX_RECONNECT_ATTEMPTS = 15
const RECONNECT_GAVE_UP = 'The connection dropped before the reply finished. Try again.'

const DEMO_REPLY = [
    "This is the demo, so I can't look at your data.",
    '',
    'When you sign in, PostHog AI can:',
    '',
    '- explain what **caused** a report',
    '- check **who is affected** with a quick query',
    '- draft a **status update** you can paste anywhere',
    '',
    'Turn off the demo in Settings, then sign in to ask about your own reports.',
].join('\n')
const DEMO_REPLY_WITH_CONTEXT = DEMO_REPLY.replace(
    "I can't look at your data.",
    "I can't read attached reports or your data."
)

export type ChatPhase = 'idle' | 'streaming' | 'reconnecting'

export interface Conversation {
    conversationId: string
    messages: ChatEntry[]
    title: string | null
    isStreaming: boolean
    phase: ChatPhase
    error: ChatError | null
    send: (text: string, context: ChatContext) => Promise<void>
    retry: () => Promise<void>
    /** Stops reading the reply. The server has no cancel for app tokens, so the run finishes there. */
    stop: () => void
    reset: () => void
}

type TurnOutcome = { kind: 'done' } | { kind: 'stopped' } | { kind: 'busy' } | { kind: 'failed'; error: ChatError }

interface TurnRequest {
    conversationId: string
    content: string | null
    traceId: string
}

function now(): string {
    return new Date().toISOString()
}

// Every caller checks `signal.aborted` after the wait, so an abort ends the wait instead of throwing.
function wait(ms: number, signal: AbortSignal): Promise<void> {
    return sleep(ms, signal).catch(() => undefined)
}

// Reconnects with `content: null` when the connection drops mid-turn. The server replays the whole turn on a reconnect,
// which the reducer handles through `resuming`.
async function streamTurn(
    request: TurnRequest,
    signal: AbortSignal,
    dispatch: (action: ChatThreadAction) => void,
    setPhase: (phase: ChatPhase) => void
): Promise<TurnOutcome> {
    let content = request.content
    let traceId = request.traceId
    let attempt = 0
    while (true) {
        let opened = false
        if (content === null) {
            dispatch({ type: 'resuming' })
        }
        try {
            const response = await openConversationStream(
                { conversationId: request.conversationId, traceId, content },
                signal
            )
            opened = true
            attempt = 0
            setPhase('streaming')
            await readConversationStream(
                response,
                (event: ConversationEvent) => dispatch({ type: 'event', event, at: now() }),
                signal
            )
            if (signal.aborted) {
                return { kind: 'stopped' }
            }
            dispatch({ type: 'finished', at: now() })
            return { kind: 'done' }
        } catch (error) {
            if (signal.aborted) {
                return { kind: 'stopped' }
            }
            if (error instanceof ApiError && error.status === 409 && content !== null) {
                return { kind: 'busy' }
            }
            if (error instanceof ApiError && error.status === 400 && content === null) {
                // The turn ended while the app was away. The stored conversation has the reply.
                try {
                    const detail = await fetchConversation(request.conversationId, signal)
                    dispatch({ type: 'hydrated', title: detail.title, messages: detail.messages, at: now() })
                    return { kind: 'done' }
                } catch {
                    return { kind: 'failed', error: { kind: 'network', message: RECONNECT_GAVE_UP } }
                }
            }
            // Before the stream opens the server may not have the message, so only a reattach retries on its own.
            const midTurn = opened || content === null
            if (midTurn && isNetworkError(error) && attempt < MAX_RECONNECT_ATTEMPTS) {
                attempt += 1
                setPhase('reconnecting')
                await wait(RECONNECT_STEP_MS * attempt, signal)
                if (signal.aborted) {
                    return { kind: 'stopped' }
                }
                content = null
                traceId = randomUUID()
                continue
            }
            return {
                kind: 'failed',
                error:
                    midTurn && isNetworkError(error)
                        ? { kind: 'network', message: RECONNECT_GAVE_UP }
                        : toChatError(error),
            }
        }
    }
}

async function playDemoReply(
    reply: string,
    signal: AbortSignal,
    dispatch: (action: ChatThreadAction) => void,
    hasContext: boolean
): Promise<TurnOutcome> {
    const event = (value: ConversationEvent): void => dispatch({ type: 'event', event: value, at: now() })
    const toolMessageId = `demo-${randomUUID()}`
    await wait(300, signal)
    if (signal.aborted) {
        return { kind: 'stopped' }
    }
    event({ type: 'message', message: { type: 'ai', id: toolMessageId, content: '', tool_calls: [] } })
    event({
        type: 'update',
        update: {
            id: toolMessageId,
            tool_call_id: 'demo',
            content: hasContext ? 'Reading the attached report…' : 'Looking at your inbox…',
        },
    })
    await wait(700, signal)
    const words = reply.split(/(\s+)/)
    for (let end = 4; end < words.length; end += 4) {
        if (signal.aborted) {
            return { kind: 'stopped' }
        }
        event({ type: 'message', message: { type: 'ai', id: 'temp-0', content: words.slice(0, end).join('') } })
        await wait(45, signal)
    }
    if (signal.aborted) {
        return { kind: 'stopped' }
    }
    event({ type: 'message', message: { type: 'ai', id: `demo-${randomUUID()}`, content: reply } })
    dispatch({ type: 'finished', at: now() })
    return { kind: 'done' }
}

export function useConversation(): Conversation {
    const demo = useDemoMode((state) => state.enabled)
    const [thread, dispatch] = useReducer(chatThreadReducer, initialChatThread)
    const [phase, setPhase] = useState<ChatPhase>('idle')
    const [error, setError] = useState<ChatError | null>(null)
    const [conversationId, setConversationId] = useState<string>(() => randomUUID())
    const conversationIdRef = useRef(conversationId)
    const controller = useRef<AbortController | null>(null)
    /** Increments per run, so a run that `reset` or unmount abandoned cannot touch newer state. */
    const runId = useRef(0)
    const inFlight = useRef(false)
    const lastPrompt = useRef<{ text: string; content: string; hasContext: boolean } | null>(null)

    useEffect(
        () => () => {
            runId.current += 1
            controller.current?.abort()
        },
        []
    )

    const execute = useCallback(
        async (prompt: { text: string; content: string; hasContext: boolean }, traceId: string): Promise<void> => {
            runId.current += 1
            const run = runId.current
            const guarded = (action: ChatThreadAction): void => {
                if (runId.current === run) {
                    dispatch(action)
                }
            }
            const guardedPhase = (next: ChatPhase): void => {
                if (runId.current === run) {
                    setPhase(next)
                }
            }
            const abort = new AbortController()
            controller.current = abort
            inFlight.current = true
            setError(null)
            setPhase('streaming')
            try {
                const request = { conversationId: conversationIdRef.current, content: prompt.content, traceId }
                let outcome = demo
                    ? await playDemoReply(
                          prompt.hasContext ? DEMO_REPLY_WITH_CONTEXT : DEMO_REPLY,
                          abort.signal,
                          guarded,
                          prompt.hasContext
                      )
                    : await streamTurn(request, abort.signal, guarded, guardedPhase)
                if (outcome.kind === 'busy') {
                    // A stopped turn is still running on the server. Show its end, then send this message.
                    guarded({ type: 'withdrawn' })
                    const previous = await streamTurn(
                        { ...request, content: null, traceId: randomUUID() },
                        abort.signal,
                        guarded,
                        guardedPhase
                    )
                    if (previous.kind === 'stopped') {
                        outcome = previous
                    } else {
                        const retryTrace = randomUUID()
                        guarded({ type: 'sent', text: prompt.text, traceId: retryTrace, at: now() })
                        outcome =
                            previous.kind === 'done'
                                ? await streamTurn(
                                      { ...request, traceId: retryTrace },
                                      abort.signal,
                                      guarded,
                                      guardedPhase
                                  )
                                : previous
                    }
                }
                if (outcome.kind === 'stopped') {
                    guarded({ type: 'stopped' })
                } else if (outcome.kind === 'busy' || outcome.kind === 'failed') {
                    const failure = outcome.kind === 'busy' ? toChatError(new ApiError(409, undefined)) : outcome.error
                    guarded({ type: 'failed', message: failure.message, at: now() })
                    if (runId.current === run) {
                        setError(failure)
                    }
                }
            } finally {
                if (runId.current === run) {
                    inFlight.current = false
                    controller.current = null
                    setPhase('idle')
                }
            }
        },
        [demo]
    )

    const send = useCallback(
        async (text: string, context: ChatContext): Promise<void> => {
            const trimmed = text.trim()
            if (!trimmed || inFlight.current) {
                return
            }
            const prompt = {
                text: trimmed,
                content: chatPrompt(trimmed, context),
                hasContext: context.kind === 'reports' && context.reports.length > 0,
            }
            lastPrompt.current = prompt
            track('mobile_chat_sent', { report_count: context.kind === 'reports' ? context.reports.length : 0 })
            const traceId = randomUUID()
            dispatch({ type: 'sent', text: trimmed, traceId, at: now() })
            await execute(prompt, traceId)
        },
        [execute]
    )

    const retry = useCallback(async (): Promise<void> => {
        const prompt = lastPrompt.current
        if (!prompt || inFlight.current) {
            return
        }
        const traceId = randomUUID()
        dispatch({ type: 'retrying', traceId })
        await execute(prompt, traceId)
    }, [execute])

    const stop = useCallback((): void => {
        controller.current?.abort()
    }, [])

    const reset = useCallback((): void => {
        runId.current += 1
        controller.current?.abort()
        controller.current = null
        inFlight.current = false
        lastPrompt.current = null
        const next = randomUUID()
        conversationIdRef.current = next
        setConversationId(next)
        setPhase('idle')
        setError(null)
        dispatch({ type: 'reset' })
    }, [])

    return {
        conversationId,
        messages: thread.entries,
        title: thread.title,
        isStreaming: phase !== 'idle',
        phase,
        error,
        send,
        retry,
        stop,
        reset,
    }
}
