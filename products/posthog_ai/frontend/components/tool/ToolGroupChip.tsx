import clsx from 'clsx'
import { type ComponentType, type ReactNode, memo } from 'react'

import {
    IconChevronDown,
    IconChevronRight,
    IconDocument,
    IconGlobe,
    IconPencil,
    IconSearch,
    IconShuffle,
    IconTerminal,
    IconTrash,
    IconWrench,
    IconAI,
} from '@posthog/icons'
import { Spinner, Tooltip } from '@posthog/lemon-ui'

import type { GroupIconKey, GroupSummary } from '../../logics/threadGroups'
import { ActivityDetails } from '../ActivityPrimitives'

/** Maps a chip icon key to its icon component. Falls back to a wrench for unrecognized kinds. */
function iconForKey(key: GroupIconKey): ComponentType<{ className?: string }> {
    switch (key) {
        case 'subagent':
            return IconAI
        case 'kind:execute':
            return IconTerminal
        case 'kind:read':
            return IconDocument
        case 'kind:edit':
            return IconPencil
        case 'kind:delete':
            return IconTrash
        case 'kind:move':
            return IconShuffle
        case 'kind:search':
            return IconSearch
        case 'kind:fetch':
            return IconGlobe
        default:
            return IconWrench
    }
}

const ICON_KEY_LABELS: Partial<Record<GroupIconKey, string>> = {
    subagent: 'Spawned a subagent',
    'kind:execute': 'Ran terminal commands',
    'kind:read': 'Read files',
    'kind:edit': 'Edited files',
    'kind:delete': 'Deleted files',
    'kind:move': 'Moved files',
    'kind:search': 'Searched the codebase',
    'kind:fetch': 'Fetched a web page',
}

function labelForIconKey(key: GroupIconKey): string {
    return ICON_KEY_LABELS[key] ?? 'Ran other tools'
}

export interface ToolGroupChipProps {
    summary: GroupSummary
    expanded: boolean
    turnComplete: boolean
    onToggle: () => void
    /** Rendered group items, shown inside the body rail when expanded. */
    children?: ReactNode
}

/**
 * A collapsed tool-call group: a clickable summary header (caret + spinner + verb-led label + icon
 * strip) standing in for a run of tool calls and reasoning. Controlled — the open state is owned by
 * the stream logic's per-group override. While the turn runs it shows the live action; once complete
 * it shows the verb-led summary.
 */
export const ToolGroupChip = memo(function ToolGroupChip({
    summary,
    expanded,
    turnComplete,
    onToggle,
    children,
}: ToolGroupChipProps): JSX.Element {
    const Caret = expanded ? IconChevronDown : IconChevronRight
    // Spin on THIS group's own in-flight tool, not the turn — a turn split across several chips
    // (by messages) must not keep finished chips spinning.
    const running = !turnComplete && summary.active && summary.liveLabel != null
    // While running, show both what's happened so far and what's happening now, so a collapsed turn
    // reads as actively-working rather than stalled.
    const label = running
        ? summary.hasCountableWork
            ? `${summary.doneLabel} · ${summary.liveLabel}`
            : (summary.liveLabel as string)
        : summary.doneLabel

    return (
        <div className="flex flex-col rounded transition-all duration-500 w-full min-w-0 gap-1 text-xs">
            <div
                className="group/group-chip flex items-center gap-1 min-w-0 select-none cursor-pointer rounded px-1 -mx-1 hover:bg-fill-button-tertiary-hover text-default"
                onClick={onToggle}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onToggle()
                    }
                }}
                role="button"
                tabIndex={0}
                aria-expanded={expanded}
                aria-label={expanded ? 'Collapse tool activity' : 'Expand tool activity'}
            >
                <Caret className="size-4 shrink-0 text-muted transition-colors group-hover/group-chip:text-default" />
                {running && <Spinner className="shrink-0 text-muted" />}
                <span className={clsx('truncate min-w-0', running && 'text-muted')}>{label}</span>
                {!expanded && summary.icons.length > 0 && (
                    <span className="ml-1 flex shrink-0 items-center gap-1.5 text-muted">
                        {summary.icons.map((key) => {
                            const Icon = iconForKey(key)
                            return (
                                <Tooltip key={key} title={labelForIconKey(key)}>
                                    <span className="flex items-center">
                                        <Icon className="size-3.5" />
                                    </span>
                                </Tooltip>
                            )
                        })}
                    </span>
                )}
            </div>
            {expanded && <ActivityDetails hasIcon={true}>{children}</ActivityDetails>}
        </div>
    )
})
