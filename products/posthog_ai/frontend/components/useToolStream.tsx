import { useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { runStreamLogic } from '../logics/runStreamLogic'
import type { ToolInvocation, ToolInvocationStatus, ToolStreamEvent } from '../types/streamTypes'
import { resolveToolCall } from './tool/toolResolver'

export interface UseToolStreamOptions {
    /** The run to subscribe to — same key `runStreamLogic` uses. */
    streamKey: string
    /**
     * Tools to react to, matched by resolved registry key (e.g. `create_insight`) OR raw wire tool name
     * (e.g. `Bash`). Omit to react to every tool.
     */
    tools?: string[]
    /** A matched tool call first appeared in the stream. */
    onStarted?: (event: ToolStreamEvent) => void
    /** A matched tool call advanced to another non-terminal status (e.g. pending → in_progress). */
    onUpdated?: (event: ToolStreamEvent) => void
    /** A matched tool call reached `completed`. Fires once. */
    onCompleted?: (event: ToolStreamEvent) => void
    /** A matched tool call reached `failed`. Fires once. */
    onFailed?: (event: ToolStreamEvent) => void
}

export type ToolStreamEventKind = 'started' | 'updated' | 'completed' | 'failed'

/** A tool invocation resolved to its registry key, filtered to the subscriber's tool set. */
export interface MatchedInvocation {
    invocation: ToolInvocation
    resolvedKey: string
}

/**
 * Diff a batch of matched invocations against the last-seen status per tool call, mutating `prev` to the
 * new baseline and returning the lifecycle events to fire. Pure aside from the `prev` mutation, so the
 * transition rules (start once, terminal once, no event when status is unchanged) are unit-testable
 * without a React harness. A tool first seen already-terminal yields both `started` and its terminal
 * event; a status held across updates yields nothing.
 */
export function diffToolStream(
    prev: Map<string, ToolInvocationStatus>,
    matched: MatchedInvocation[]
): { kind: ToolStreamEventKind; event: ToolStreamEvent }[] {
    const out: { kind: ToolStreamEventKind; event: ToolStreamEvent }[] = []
    for (const { invocation, resolvedKey } of matched) {
        const status = invocation.status
        const prevStatus = prev.get(invocation.toolCallId)
        if (prevStatus === status) {
            continue
        }
        prev.set(invocation.toolCallId, status)
        const event: ToolStreamEvent = { invocation, resolvedKey }
        if (prevStatus === undefined) {
            out.push({ kind: 'started', event })
            if (status === 'completed') {
                out.push({ kind: 'completed', event })
            } else if (status === 'failed') {
                out.push({ kind: 'failed', event })
            }
        } else if (status === 'completed') {
            out.push({ kind: 'completed', event })
        } else if (status === 'failed') {
            out.push({ kind: 'failed', event })
        } else {
            out.push({ kind: 'updated', event })
        }
    }
    return out
}

/**
 * Subscribe to streamed tool-call lifecycle for a specific set of tools and react to changes — the
 * event-listener the old langgraph `useMaxTool({ callback })` provided, generalized to the surface.
 *
 * Diffs `runStreamLogic`'s `toolInvocations` map on the consumer side (the folder deliberately avoids
 * `kea-subscriptions`). Opening an already-finished run fires nothing: the first observation seeds the
 * baseline silently, so only transitions observed *after* mount fire.
 */
export function useToolStream({
    streamKey,
    tools,
    onStarted,
    onUpdated,
    onCompleted,
    onFailed,
}: UseToolStreamOptions): void {
    const { toolInvocations } = useValues(runStreamLogic({ streamKey }))

    // Keep callbacks in a ref so passing inline closures never re-runs (and thus re-seeds) the effect.
    const handlersRef = useRef({ onStarted, onUpdated, onCompleted, onFailed })
    handlersRef.current = { onStarted, onUpdated, onCompleted, onFailed }

    const prev = useRef<Map<string, ToolInvocationStatus>>(new Map())
    const seeded = useRef(false)

    const toolsKey = useMemo(() => (tools ? tools.join(' ') : ''), [tools])

    useEffect(() => {
        const matched: MatchedInvocation[] = []
        for (const invocation of toolInvocations.values()) {
            const { resolvedKey } = resolveToolCall(invocation)
            if (!tools || tools.includes(resolvedKey) || tools.includes(invocation.rawToolName)) {
                matched.push({ invocation, resolvedKey })
            }
        }

        // First observation: seed the baseline silently so replaying a finished run (or attaching
        // mid-flight) doesn't replay a burst of started/completed callbacks. Only later transitions fire.
        if (!seeded.current) {
            seeded.current = true
            for (const { invocation } of matched) {
                prev.current.set(invocation.toolCallId, invocation.status)
            }
            return
        }

        const handlers = handlersRef.current
        for (const { kind, event } of diffToolStream(prev.current, matched)) {
            if (kind === 'started') {
                handlers.onStarted?.(event)
            } else if (kind === 'updated') {
                handlers.onUpdated?.(event)
            } else if (kind === 'completed') {
                handlers.onCompleted?.(event)
            } else {
                handlers.onFailed?.(event)
            }
        }
        // handlersRef is stable; toolsKey stands in for the `tools` array content.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [toolInvocations, streamKey, toolsKey])
}

export type ToolStreamListenerProps = UseToolStreamOptions

/**
 * Render-less declarative form of `useToolStream` — drop `<ToolStreamListener streamKey tools onCompleted />`
 * into JSX to react to streamed tool changes for as long as it's mounted. Symmetric with `<AgentContext>`.
 */
export function ToolStreamListener(props: ToolStreamListenerProps): null {
    useToolStream(props)
    return null
}
