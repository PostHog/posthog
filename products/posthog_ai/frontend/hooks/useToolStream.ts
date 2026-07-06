import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { uuid } from 'lib/utils/dom'

import { toolStreamEventsLogic } from '../logics/toolStreamEventsLogic'
import type { ToolStreamEvent } from '../types/streamTypes'

export interface UseToolStreamListenerOptions {
    /** Resolved tool names to match, or `'*'` for every tool. */
    tools: string[] | '*'
    onEvent: (event: ToolStreamEvent) => void
    /** When true, replay-sourced events are delivered too. Defaults to false (live only). */
    includeReplay?: boolean
}

/**
 * Subscribes to tool-call lifecycle events for the given (resolved) tool names. Registers once per
 * mount under a stable listener id; the latest `onEvent` is held in a ref so re-renders don't churn
 * the registration. Deregisters on unmount.
 */
export function useToolStreamListener({ tools, onEvent, includeReplay }: UseToolStreamListenerOptions): void {
    const { registerToolListener, deregisterToolListener } = useActions(toolStreamEventsLogic)
    const listenerIdRef = useRef<string>(`tool-listener-${uuid()}`)
    const onEventRef = useRef(onEvent)
    onEventRef.current = onEvent

    // Re-register when the matched tools or replay flag change (not on every onEvent identity change).
    const toolsKey = tools === '*' ? '*' : tools.join(',')

    useEffect(() => {
        const listenerId = listenerIdRef.current
        registerToolListener(listenerId, {
            tools,
            includeReplay,
            onEvent: (event) => onEventRef.current(event),
        })
        return () => deregisterToolListener(listenerId)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [toolsKey, includeReplay, registerToolListener, deregisterToolListener])
}
