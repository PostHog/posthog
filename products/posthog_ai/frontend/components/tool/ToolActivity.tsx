import { type ReactNode } from 'react'

import { IconWarning, IconWrench } from '@posthog/icons'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { Activity } from '../ActivityPrimitives'
import type { ActivityStatus } from '../ActivityPrimitives'
import { VirtualizedThread } from '../VirtualizedThread'
import { resolveToolCallStatus } from './toolContentUtils'

export interface ToolActivityProps {
    message: ToolCallMessage
    /** Registry icon; defaults to the generic wrench. */
    icon?: ReactNode
    /** Header line 1. */
    title: ReactNode
    /** Salient input (command, path, URL), shown inside the expanded details. */
    subtitle?: ReactNode
    /** Collapsible body: streamed/expandable output (Bash output, file preview, diff, …). */
    body?: ReactNode
    /** Always-visible content below the header: data visualizations, the question recap, …. */
    children?: ReactNode
    /** Turn-level signals so a still-incomplete tool reads as loading vs cancelled vs idle. */
    turnComplete?: boolean
    turnCancelled?: boolean
}

/**
 * Bridges a sandbox tool call onto the shared `Activity` accordion: maps the tool's status to
 * Activity's status/icons, surfaces a failure line, and routes per-tool content to either the
 * manually expanded body (`body` → Activity `details`) or the always-visible
 * region (`children`). Every sandbox tool card renders through this.
 */
export function ToolActivity({
    message,
    icon,
    title,
    subtitle,
    body,
    children,
    turnComplete,
    turnCancelled,
}: ToolActivityProps): JSX.Element {
    const pauseFollowing = VirtualizedThread.usePauseFollowing()
    const { isLoading, isFailed, wasCancelled } = resolveToolCallStatus(message.status, !!turnCancelled, !!turnComplete)
    const status: ActivityStatus = isFailed ? 'failed' : isLoading ? 'in_progress' : 'completed'

    // Failures remain readable without opening the raw input/output.
    const errorLine =
        isFailed && message.error?.message ? <div className="text-danger">{message.error.message}</div> : null
    const alwaysVisible = errorLine ? (
        <div className="flex flex-col gap-2">
            {errorLine}
            {children}
        </div>
    ) : (
        (children ?? null)
    )

    return (
        <Activity
            id={message.id}
            title={
                <span className="flex items-center gap-2 min-w-0">
                    <span className="truncate">{title}</span>
                    <span className="text-muted shrink-0 font-normal">
                        {isFailed
                            ? 'Failed'
                            : wasCancelled
                              ? 'Canceled'
                              : isLoading
                                ? message.status === 'pending'
                                    ? 'Pending'
                                    : 'Running'
                                : message.status === 'completed'
                                  ? 'Completed'
                                  : 'Incomplete'}
                    </span>
                </span>
            }
            status={status}
            icon={icon ?? <IconWrench />}
            showProgressIcon
            showCompletionIcon={!wasCancelled}
            failedIcon={<IconWarning className="text-danger size-3" />}
            animate={false}
            autoExpand={false}
            onToggleDetails={(expanded) => {
                if (expanded) {
                    pauseFollowing()
                }
            }}
            details={
                subtitle || body ? (
                    <div className="flex flex-col gap-2 min-w-0">
                        {subtitle && <div className="text-muted break-words">{subtitle}</div>}
                        {body}
                    </div>
                ) : undefined
            }
        >
            {alwaysVisible}
        </Activity>
    )
}
