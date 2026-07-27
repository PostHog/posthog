import { type ReactNode } from 'react'

import { IconWarning, IconWrench } from '@posthog/icons'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { Activity } from '../ActivityPrimitives'
import type { ActivityStatus } from '../ActivityPrimitives'
import { resolveToolCallStatus } from './toolContentUtils'

export interface ToolActivityProps {
    message: ToolCallMessage
    /** Registry icon; defaults to the generic wrench. */
    icon?: ReactNode
    /** Header line 1. */
    title: ReactNode
    /** Header line 2 — the tool's salient input (command, path, url, …) where applicable. */
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
 * collapsible body (`body` → Activity `details`, auto-expands while running) or the always-visible
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
    const { isLoading, isFailed, wasCancelled } = resolveToolCallStatus(message.status, !!turnCancelled, !!turnComplete)
    const status: ActivityStatus = isFailed ? 'failed' : isLoading ? 'in_progress' : 'completed'

    // Activity has no "cancelled" status — render it as a neutral terminal row (no check) with a marker
    // on the subtitle, or the title when there's no subtitle.
    const cancelledMarker = wasCancelled ? <span className="text-muted"> (cancelled)</span> : null
    const renderedTitle =
        !subtitle && cancelledMarker ? (
            <>
                {title}
                {cancelledMarker}
            </>
        ) : (
            title
        )
    const renderedSubtitle =
        subtitle && cancelledMarker ? (
            <>
                {subtitle}
                {cancelledMarker}
            </>
        ) : (
            subtitle
        )

    // The failure message lives in the always-visible region so it shows even though a failed tool's
    // details auto-collapse.
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
            title={renderedTitle}
            subtitle={renderedSubtitle}
            status={status}
            icon={icon ?? <IconWrench />}
            showProgressIcon
            showCompletionIcon={!wasCancelled}
            failedIcon={<IconWarning className="text-danger size-3" />}
            details={body}
        >
            {alwaysVisible}
        </Activity>
    )
}
