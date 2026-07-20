import clsx from 'clsx'
import React, { useLayoutEffect, useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { MarkdownMessage } from '../messages/MarkdownMessage'

export type ActivityStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

export function ShimmeringContent({ children }: { children: React.ReactNode }): JSX.Element {
    const isTextContent = typeof children === 'string'

    if (isTextContent) {
        return (
            <span
                className="bg-clip-text text-transparent"
                style={{
                    backgroundImage:
                        'linear-gradient(in oklch 90deg, var(--text-3000), var(--muted-3000), var(--trace-3000), var(--muted-3000), var(--text-3000))',
                    backgroundSize: '200% 100%',
                    animation: 'shimmer 3s linear infinite',
                }}
            >
                {children}
            </span>
        )
    }

    return (
        <span
            className="inline-flex min-w-0 max-w-full"
            style={{
                animation: 'shimmer-opacity 3s linear infinite',
            }}
        >
            {children}
        </span>
    )
}

function activitySubstepText(content: string, isInProgress: boolean): string {
    if (content.at(0) === '[' && content.at(-1) === ')') {
        // Skip ... for web search `updates`, where each is a Markdown-formatted link to a search result.
        return content
    }
    if (!content.endsWith('...') && !content.endsWith('\u2026') && !content.endsWith('.') && isInProgress) {
        return content + '...'
    } else if ((content.endsWith('...') || content.endsWith('\u2026')) && !isInProgress) {
        return content.replace(/\u2026/g, '').replace(/[.]/g, '')
    }
    return content
}

export function ActivityStatusIcon(_props: {
    status: ActivityStatus
    showCompletionIcon?: boolean
    showProgressIcon?: boolean
    failedIcon?: React.ReactNode
}): JSX.Element | null {
    // Intentionally renders nothing — kept as a no-op so the Activity prop chain and facade export stay stable.
    return null
}

export function ActivityHeader({
    title,
    children,
    status,
    icon,
    animate = true,
    hasDetails,
    isDetailsExpanded,
    onToggleDetails,
    showCompletionIcon = true,
    showProgressIcon = false,
    failedIcon,
}: {
    title: React.ReactNode
    children?: React.ReactNode
    status: ActivityStatus
    icon?: React.ReactNode
    animate?: boolean
    hasDetails: boolean
    isDetailsExpanded: boolean
    onToggleDetails: () => void
    showCompletionIcon?: boolean
    showProgressIcon?: boolean
    failedIcon?: React.ReactNode
}): JSX.Element {
    const isPending = status === 'pending'
    const isInProgress = status === 'in_progress'
    const isFailed = status === 'failed'

    const titleNode = (
        <div className="min-w-0 min-h-5 flex items-center">
            {isInProgress && animate ? (
                <ShimmeringContent>{title}</ShimmeringContent>
            ) : (
                <span className={clsx('inline-flex', isInProgress && 'text-muted')}>{title}</span>
            )}
        </div>
    )
    const statusIcon = (
        <ActivityStatusIcon
            status={status}
            showCompletionIcon={showCompletionIcon}
            showProgressIcon={showProgressIcon}
            failedIcon={failedIcon}
        />
    )

    return (
        <div
            className={clsx(
                // Explicit transition properties, not transition-all: `all` also catches inherited
                // scrollbar-color flips from the scrolling ancestor, starting hundreds of no-op
                // transitions (and full-document style recalcs) whenever the thread is hovered.
                'group/activity-header transition-colors duration-500 flex select-none min-w-0',
                isPending && 'text-muted',
                isFailed && 'text-danger',
                !isInProgress && !isPending && !isFailed && 'text-default',
                hasDetails ? 'cursor-pointer' : 'cursor-default',
                hasDetails && 'rounded px-1 -mx-1 hover:bg-fill-button-tertiary-hover',
                hasDetails && isDetailsExpanded && 'bg-fill-button-tertiary-active'
            )}
            onClick={hasDetails ? onToggleDetails : undefined}
            onKeyDown={
                hasDetails
                    ? (e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              onToggleDetails()
                          }
                      }
                    : undefined
            }
            role={hasDetails ? 'button' : undefined}
            tabIndex={hasDetails ? 0 : undefined}
            aria-expanded={hasDetails ? isDetailsExpanded : undefined}
            aria-label={hasDetails ? (isDetailsExpanded ? 'Collapse history' : 'Expand history') : undefined}
        >
            {icon && (
                <div className="relative flex items-center justify-center size-5 shrink-0 overflow-hidden">
                    <span
                        className={clsx(
                            'inline-flex transition-[color,transform,opacity] duration-200 ease-out',
                            isInProgress && 'text-muted',
                            hasDetails &&
                                'group-hover/activity-header:-translate-x-1 group-hover/activity-header:scale-90 group-hover/activity-header:opacity-0 group-focus-within/activity-header:-translate-x-1 group-focus-within/activity-header:scale-90 group-focus-within/activity-header:opacity-0'
                        )}
                    >
                        {isInProgress && animate ? <ShimmeringContent>{icon}</ShimmeringContent> : icon}
                    </span>
                    {hasDetails && (
                        <span className="absolute inline-flex translate-x-1 scale-90 text-tertiary opacity-0 transition-[color,transform,opacity] duration-200 ease-out group-hover/activity-header:translate-x-0 group-hover/activity-header:scale-100 group-hover/activity-header:text-primary group-hover/activity-header:opacity-100 group-focus-within/activity-header:translate-x-0 group-focus-within/activity-header:scale-100 group-focus-within/activity-header:text-primary group-focus-within/activity-header:opacity-100">
                            <IconChevronDown className="size-5" />
                        </span>
                    )}
                </div>
            )}
            <div className="flex items-center gap-1 flex-1 min-w-0">
                {children ? (
                    // The title/subtitle column grows to fill the row, so the subtitle (second line) gets the
                    // full available width before it truncates.
                    <div className="flex flex-col flex-1 min-w-0">
                        {/* Status icon rides the first line with the title; the second line is the subtitle. */}
                        <div className="flex items-center gap-1 min-w-0">
                            {titleNode}
                            {statusIcon}
                        </div>
                        <div className="text-muted truncate min-w-0">{children}</div>
                    </div>
                ) : (
                    titleNode
                )}
                {!children && statusIcon}
            </div>
        </div>
    )
}

export function ActivitySubsteps({
    id,
    substeps,
    status,
}: {
    id: string
    substeps: string[]
    status: ActivityStatus
}): JSX.Element {
    const isCompleted = status === 'completed'
    const isFailed = status === 'failed'

    return (
        <>
            {substeps.map((substep, substepIndex) => {
                const isCurrentSubstep = substepIndex === substeps.length - 1
                const isCompletedSubstep = substepIndex < substeps.length - 1 || isCompleted

                return (
                    <div key={substepIndex} className="animate-fade-in">
                        <MarkdownMessage
                            id={id}
                            className={clsx(
                                'leading-relaxed',
                                isFailed && 'text-danger',
                                !isFailed && isCompletedSubstep && 'text-muted',
                                !isFailed && isCurrentSubstep && !isCompleted && 'text-secondary'
                            )}
                            content={activitySubstepText(substep ?? '', status === 'in_progress')}
                        />
                    </div>
                )
            })}
        </>
    )
}

export function ActivityDetails({ children, hasIcon }: { children: React.ReactNode; hasIcon: boolean }): JSX.Element {
    return (
        <div className={clsx('space-y-1 border-l-2 border-border-secondary', hasIcon && 'pl-3.5 ml-[calc(0.775rem)]')}>
            {children}
        </div>
    )
}

export function ActivityToggleSection({
    title,
    summary,
    tooltip,
    children,
}: {
    title: React.ReactNode
    summary?: React.ReactNode
    tooltip?: string
    children: React.ReactNode
}): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)

    return (
        <div className="flex flex-col gap-1">
            <LemonButton
                size="xxsmall"
                type="tertiary"
                onClick={(e) => {
                    e.stopPropagation()
                    setIsExpanded(!isExpanded)
                }}
                tooltip={tooltip}
                tooltipPlacement="top-start"
                className="w-fit"
            >
                <span className="flex items-center gap-1">
                    <b>{title}</b>
                    {summary && <span className="text-secondary">{summary}</span>}
                    <span className={clsx('transform transition-transform', isExpanded && 'rotate-90')}>
                        <IconChevronRight />
                    </span>
                </span>
            </LemonButton>
            {isExpanded && children}
        </div>
    )
}

export function Activity({
    id,
    title,
    subtitle,
    status,
    icon,
    animate = true,
    showCompletionIcon = true,
    showProgressIcon = false,
    failedIcon,
    substeps = [],
    details = null,
    children = null,
}: {
    id: string
    title: React.ReactNode
    subtitle?: React.ReactNode
    status: ActivityStatus
    icon?: React.ReactNode
    animate?: boolean
    showCompletionIcon?: boolean
    showProgressIcon?: boolean
    failedIcon?: React.ReactNode
    substeps?: string[]
    details?: React.ReactNode
    children?: React.ReactNode
}): JSX.Element {
    const hasDetails = substeps.length > 0 || !!details
    const shouldExpandDetails = hasDetails && status !== 'completed' && status !== 'failed'
    const [isDetailsExpanded, setIsDetailsExpanded] = useState(shouldExpandDetails)

    useLayoutEffect(() => {
        setIsDetailsExpanded(shouldExpandDetails)
    }, [shouldExpandDetails])

    return (
        <div className="flex flex-col rounded w-full min-w-0 gap-1 text-xs">
            <ActivityHeader
                title={title}
                status={status}
                icon={icon}
                animate={animate}
                hasDetails={hasDetails}
                isDetailsExpanded={isDetailsExpanded}
                onToggleDetails={() => setIsDetailsExpanded(!isDetailsExpanded)}
                showCompletionIcon={showCompletionIcon}
                showProgressIcon={showProgressIcon}
                failedIcon={failedIcon}
            >
                {subtitle}
            </ActivityHeader>
            {isDetailsExpanded && hasDetails && (
                <ActivityDetails hasIcon={!!icon}>
                    {substeps.length > 0 && <ActivitySubsteps id={id} substeps={substeps} status={status} />}
                    {details}
                </ActivityDetails>
            )}
            {children}
        </div>
    )
}
