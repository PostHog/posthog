import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { uuid } from 'lib/utils/dom'

import { toolStreamEventsLogic } from '../logics/toolStreamEventsLogic'
import type { RunLifecycleEvent, ToolStreamEvent } from '../types/streamTypes'
import { resolveToolCall } from '../utils/toolResolver'

/** When the matched apply-back reaction fires: on tool completion or turn end. */
export type ApplyOn = 'tool_call_completed' | 'turn_end'

export interface McpToolApplyContext {
    /** The parsed inner MCP tool args (the exec `command` payload), or null when unparseable. */
    innerInput: Record<string, unknown> | null
}

export interface UseMcpToolApplyBackOptions {
    /**
     * Resolved tool names to match (the bus's resolved `toolName`), or `'*'` for every tool.
     */
    tools: string[] | '*'
    /** Called with the matching event and the parsed inner args (via `resolveToolCall`). */
    onApply: (event: ToolStreamEvent, context: McpToolApplyContext) => void
    /** When false, no apply-back listener is registered. Defaults to true. */
    active?: boolean
    /**
     * `'turn_end'` (default): apply the last matching completion once when the foreground turn ends.
     * `'tool_call_completed'`: apply each matching tool when it completes.
     */
    applyOn?: ApplyOn
}

/**
 * Reacts to the foreground run's MCP tool calls — the seam for "the agent generated a query, apply it
 * to the open editor". Always foreground-gated (only the run rendered in the side panel the user is
 * watching) and replay-excluded, so a background run or a reload never triggers a reaction. In
 * `'turn_end'` mode the last matching completed event wins and `onApply` fires once when the turn
 * finishes; `'tool_call_completed'` fires per matching completion.
 */
export function useMcpToolApplyBack({
    tools,
    onApply,
    active = true,
    applyOn = 'turn_end',
}: UseMcpToolApplyBackOptions): void {
    const { registerToolListener, deregisterToolListener } = useActions(toolStreamEventsLogic)
    const listenerIdRef = useRef<string>(`mcp-apply-back-${uuid()}`)

    // Latest callback + mode held in refs so re-renders never churn the (closure-holding) registration.
    const onApplyRef = useRef(onApply)
    onApplyRef.current = onApply
    const applyOnRef = useRef(applyOn)
    applyOnRef.current = applyOn
    // Turn-end mode: the last matching completed event, flushed when the turn or run ends.
    const bufferedEventRef = useRef<ToolStreamEvent | null>(null)

    const toolsKey = tools === '*' ? '*' : [...tools].sort().join(',')

    useEffect(() => {
        const listenerId = listenerIdRef.current
        bufferedEventRef.current = null

        if (!active) {
            return
        }

        const apply = (event: ToolStreamEvent): void => {
            // The bus event carries no inner args — re-parse the exec `command` off the invocation.
            const innerInput = resolveToolCall(event.invocation).innerInput ?? null
            onApplyRef.current(event, { innerInput })
        }

        const applyBufferedEvent = (): void => {
            if (applyOnRef.current !== 'turn_end') {
                return
            }
            const buffered = bufferedEventRef.current
            if (!buffered) {
                return
            }
            // Clear before applying so duplicate lifecycle signals can't double-apply and the next
            // turn on this stream starts from an empty buffer.
            bufferedEventRef.current = null
            apply(buffered)
        }

        registerToolListener(listenerId, {
            tools,
            foregroundOnly: true,
            includeReplay: false,
            onEvent: (event: ToolStreamEvent) => {
                if (event.phase !== 'completed') {
                    return
                }
                if (applyOnRef.current === 'tool_call_completed') {
                    apply(event)
                    return
                }
                // Turn-end mode: remember the latest match; a later completion supersedes it.
                bufferedEventRef.current = event
            },
            onTurnComplete: applyBufferedEvent,
            onRunTerminal: (_event: RunLifecycleEvent) => applyBufferedEvent(),
            // A different foreground run is now being watched — drop any buffered match from the previous
            // one. Delivered by the bus (which listens to `foregroundStreamLogic`), so foreground changes
            // never re-render the consuming component.
            onForegroundChange: () => {
                bufferedEventRef.current = null
            },
        })
        return () => deregisterToolListener(listenerId)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active, toolsKey, registerToolListener, deregisterToolListener])
}
