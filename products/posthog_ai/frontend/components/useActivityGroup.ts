import { type ReactNode, useEffect, useState } from 'react'

import type { ThreadItem, ToolInvocation } from '../types/streamTypes'
import { type ThreadActivityGroup, activityWindow } from '../utils/groupThreadActivity'
import { resolveToolCall } from '../utils/toolResolver'
import { lookupToolRenderer } from './tool/toolRegistry'
import { VirtualizedThread } from './VirtualizedThread'

function groupLabel({
    active,
    cancelled,
    waitingForInput,
    thoughtsOnly,
}: {
    active: boolean
    cancelled: boolean
    waitingForInput: boolean
    thoughtsOnly: boolean
}): string {
    if (waitingForInput) {
        return 'Waiting for you'
    }
    if (active) {
        return thoughtsOnly ? 'Thinking' : 'Working'
    }
    if (cancelled) {
        return 'Stopped'
    }
    return thoughtsOnly ? 'Thought' : 'Worked'
}

export interface ActivityGroupProps {
    group: ThreadActivityGroup
    toolInvocations: Map<string, ToolInvocation>
    active: boolean
    cancelled: boolean
    waitingForInput?: boolean
    renderItem: (item: ThreadItem) => ReactNode
}

/**
 * Everything an activity group shows, for every skin: its label, the tool calls, and the rows to list
 * when open. An open group freezes its rows while the reader is scrolled away from the bottom, so rows
 * never insert above what they are reading; `newCount` counts what arrived since, and `showNew` lets it in.
 */
export function useActivityGroup({
    group,
    toolInvocations,
    active,
    cancelled,
    waitingForInput = false,
}: ActivityGroupProps): {
    label: string
    currentLabel: string
    calls: ToolInvocation[]
    thoughtsOnly: boolean
    expanded: boolean
    setExpanded: (expanded: boolean) => void
    window: ReturnType<typeof activityWindow<ThreadItem>>
    showMiddle: boolean
    toggleMiddle: () => void
    visibleThoughtsOnly: boolean
    newCount: number
    showNew: () => void
} {
    const pauseFollowing = VirtualizedThread.usePauseFollowing()
    const isFollowing = VirtualizedThread.useIsFollowing()
    const [expanded, setExpandedState] = useState(false)
    const [visibleIds, setVisibleIds] = useState<string[]>([])
    const [showMiddle, setShowMiddle] = useState(false)
    useEffect(() => {
        if (expanded && isFollowing) {
            setVisibleIds((previous) =>
                previous.length === group.items.length && previous.every((id, index) => id === group.items[index].id)
                    ? previous
                    : group.items.map((item) => item.id)
            )
        }
    }, [expanded, isFollowing, group.items])

    const calls = group.items.flatMap((item) => {
        const call = item.toolCallId ? toolInvocations.get(item.toolCallId) : undefined
        return call ? [call] : []
    })
    const thoughtsOnly = group.items.every((item) => item.type === 'assistant_thought')
    const label = groupLabel({ active, cancelled, waitingForInput, thoughtsOnly })
    const current = active
        ? calls.findLast((call) => call.status === 'in_progress' || call.status === 'pending')
        : undefined
    const resolved = current ? resolveToolCall(current) : undefined
    const currentLabel =
        current && resolved
            ? current.title || lookupToolRenderer(resolved.resolvedKey, !!resolved.innerToolName).displayName
            : 'Thinking…'

    const visible = new Set(visibleIds)
    const snapshot = isFollowing ? group.items : group.items.filter((item) => visible.has(item.id))
    const allIds = (): string[] => group.items.map((item) => item.id)

    return {
        label,
        currentLabel,
        calls,
        thoughtsOnly,
        expanded,
        setExpanded: (next) => {
            if (next && !expanded) {
                setVisibleIds(allIds())
            }
            setExpandedState(next)
        },
        window: activityWindow(snapshot, showMiddle),
        showMiddle,
        toggleMiddle: () => {
            pauseFollowing()
            setShowMiddle(!showMiddle)
        },
        visibleThoughtsOnly: snapshot.every((item) => item.type === 'assistant_thought'),
        newCount: isFollowing ? 0 : group.items.filter((item) => !visible.has(item.id)).length,
        showNew: () => setVisibleIds(allIds()),
    }
}
