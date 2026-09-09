import { Fragment, type ReactNode, useEffect, useState } from 'react'

import { IconChevronRight, IconSpinner } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { MarkdownMessage } from '../messages/MarkdownMessage'
import type { ThreadItem, ToolInvocation } from '../types/streamTypes'
import {
    activityWindow,
    groupConsecutiveTools,
    type ThreadActivityGroup as ActivityGroup,
} from '../utils/groupThreadActivity'
import { resolveToolCall } from '../utils/toolResolver'
import { ActivityDisclosure } from './ActivityDisclosure'
import { ActivityElapsedTime } from './ActivityElapsedTime'
import { Activity } from './ActivityPrimitives'
import { lookupToolRenderer } from './tool/toolRegistry'
import { VirtualizedThread } from './VirtualizedThread'

export function ThreadActivityGroup({
    group,
    toolInvocations,
    active,
    cancelled,
    waitingForInput = false,
    renderItem,
}: {
    group: ActivityGroup
    toolInvocations: Map<string, ToolInvocation>
    active: boolean
    cancelled: boolean
    waitingForInput?: boolean
    renderItem: (item: ThreadItem) => ReactNode
}): JSX.Element {
    const pauseFollowing = VirtualizedThread.usePauseFollowing()
    const isFollowing = VirtualizedThread.useIsFollowing()
    const [expanded, setExpanded] = useState(false)
    const [visibleIds, setVisibleIds] = useState<string[]>([])
    const [middlePage, setMiddlePage] = useState(0)
    const [showMiddle, setShowMiddle] = useState(false)
    const [showFailures, setShowFailures] = useState(false)
    const [failurePage, setFailurePage] = useState(0)
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
    const failures = calls.filter((call) => call.status === 'failed')
    const thoughtsOnly = group.items.every((item) => item.type === 'assistant_thought')
    const activeLabel = thoughtsOnly ? 'Thinking' : 'Working'
    const finishedLabel = thoughtsOnly ? 'Thought' : 'Worked'
    const label = waitingForInput ? 'Waiting for you' : active ? activeLabel : cancelled ? 'Stopped' : finishedLabel
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
    const visibleThoughtsOnly = snapshot.every((item) => item.type === 'assistant_thought')
    const chainKeys = new Map(
        groupConsecutiveTools(group.items, toolInvocations).flatMap((chain) =>
            chain.map((item) => [item.id, chain[0].id] as const)
        )
    )
    const window = activityWindow(snapshot, middlePage)
    const displayedIds = new Set(
        [...window.first, ...(showMiddle ? window.middle : []), ...window.last].map((item) => item.id)
    )
    const additionalFailures = snapshot.filter(
        (item) =>
            !displayedIds.has(item.id) && item.toolCallId && toolInvocations.get(item.toolCallId)?.status === 'failed'
    )
    const failurePageCount = Math.ceil(additionalFailures.length / 10)
    const currentFailurePage = Math.max(0, Math.min(failurePage, failurePageCount - 1))
    const newCount = isFollowing ? 0 : group.items.filter((item) => !visible.has(item.id)).length
    const toggle = (): void => {
        if (!expanded) {
            setVisibleIds(group.items.map((item) => item.id))
        }
        setExpanded(!expanded)
    }
    const individualRows = (items: ThreadItem[]): ReactNode =>
        items.map((item) => (
            <Fragment key={item.id}>
                {visibleThoughtsOnly ? (
                    <div className="text-muted">
                        <MarkdownMessage id={item.id} content={item.text ?? ''} />
                    </div>
                ) : (
                    renderItem(item)
                )}
            </Fragment>
        ))
    const rows = (items: ThreadItem[]): ReactNode =>
        groupConsecutiveTools(items, toolInvocations).map((chain) => {
            if (chain.length === 1) {
                return <Fragment key={chain[0].id}>{individualRows(chain)}</Fragment>
            }
            const chainCalls = chain.map((item) => toolInvocations.get(item.toolCallId!)!)
            const resolved = resolveToolCall(chainCalls[0])
            const entry = lookupToolRenderer(resolved.resolvedKey, !!resolved.innerToolName)
            const failed = chainCalls.filter((call) => call.status === 'failed').length
            const running =
                active && chainCalls.some((call) => call.status === 'pending' || call.status === 'in_progress')
            return (
                <div key={chainKeys.get(chain[0].id)} data-attr="thread-tool-chain">
                    <Activity
                        id={`chain-${chain[0].id}`}
                        title={
                            <span className="flex items-center gap-2 min-w-0">
                                <span className="truncate">{entry.displayName}</span>
                                <span className="text-muted shrink-0">· {chain.length} calls</span>
                                {failed > 0 && <span className="text-danger shrink-0">· {failed} failed</span>}
                            </span>
                        }
                        icon={entry.icon}
                        status={running ? 'in_progress' : 'completed'}
                        animate={false}
                        autoExpand={false}
                        details={<div className="flex flex-col gap-1 min-w-0">{individualRows(chain)}</div>}
                    />
                </div>
            )
        })

    return (
        <div
            className="flex flex-col gap-1 min-w-0 text-[13px] leading-5 font-normal"
            data-attr="thread-activity-group"
        >
            <LemonButton
                type="tertiary"
                size="small"
                fullWidth
                onClick={toggle}
                aria-expanded={expanded}
                aria-controls={`activity-details-${group.id}`}
                data-attr="thread-activity-toggle"
                icon={
                    <span className="flex size-5 items-center justify-center">
                        <IconChevronRight
                            className={`text-[13px] transition-transform duration-150 ease-out motion-reduce:transition-none ${expanded ? 'rotate-90' : ''}`}
                        />
                    </span>
                }
            >
                <span className="flex items-center gap-2 flex-wrap min-w-0 text-[13px] leading-5 font-normal">
                    <span>{label}</span>
                    {active && !waitingForInput && <IconSpinner className="animate-spin motion-reduce:animate-none" />}
                    {!waitingForInput && (
                        <ActivityElapsedTime startedAt={group.startedAt} endedAt={group.endedAt} active={active} />
                    )}
                    {calls.length > 0 && (
                        <span
                            className="text-muted tabular-nums"
                            title="Tool calls in this activity group, not the whole response. Calls shown separately are not included."
                        >
                            ·{' '}
                            <span
                                key={calls.length}
                                className="inline-block animate-fade-in [animation-duration:150ms] motion-reduce:animate-none"
                            >
                                {calls.length}
                            </span>{' '}
                            tool {calls.length === 1 ? 'call' : 'calls'}
                        </span>
                    )}
                    {failures.length > 0 && (
                        <span className="text-danger">
                            · {failures.length} tool {failures.length === 1 ? 'call' : 'calls'} failed
                        </span>
                    )}
                </span>
            </LemonButton>
            {active && (!thoughtsOnly || waitingForInput) && (
                <div className="pl-9 text-muted truncate h-5" title={currentLabel}>
                    {waitingForInput ? 'Review the request below' : currentLabel}
                </div>
            )}
            <ActivityDisclosure open={expanded} id={`activity-details-${group.id}`}>
                <div className="ml-3 pl-3 border-l border-border-secondary flex flex-col gap-1 min-w-0">
                    {(additionalFailures.length > 0 || showFailures) && (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            status="danger"
                            data-attr="thread-activity-failures"
                            aria-expanded={showFailures}
                            aria-controls={`activity-failures-${group.id}`}
                            onClick={() => {
                                pauseFollowing()
                                setShowFailures(!showFailures)
                            }}
                        >
                            {showFailures
                                ? 'Hide additional failed calls'
                                : `Show ${additionalFailures.length} hidden failed ${additionalFailures.length === 1 ? 'call' : 'calls'}`}
                        </LemonButton>
                    )}
                    <ActivityDisclosure open={showFailures} id={`activity-failures-${group.id}`}>
                        <div
                            className="flex flex-col gap-1 pb-2 border-b border-border-secondary"
                            data-attr="thread-activity-additional-failures"
                        >
                            {additionalFailures.length === 0 && (
                                <span className="text-muted">All failed calls are visible in the activity below.</span>
                            )}
                            {failurePageCount > 1 && (
                                <div className="flex items-center gap-2 flex-wrap text-muted">
                                    <LemonButton
                                        size="xsmall"
                                        type="tertiary"
                                        data-attr="thread-activity-failures-previous"
                                        disabledReason={currentFailurePage === 0 ? 'First page' : undefined}
                                        onClick={() => {
                                            pauseFollowing()
                                            setFailurePage(currentFailurePage - 1)
                                        }}
                                    >
                                        Previous
                                    </LemonButton>
                                    <span>
                                        Failed calls {currentFailurePage * 10 + 1}–
                                        {Math.min((currentFailurePage + 1) * 10, additionalFailures.length)} of{' '}
                                        {additionalFailures.length}
                                    </span>
                                    <LemonButton
                                        size="xsmall"
                                        type="tertiary"
                                        data-attr="thread-activity-failures-next"
                                        disabledReason={
                                            currentFailurePage + 1 === failurePageCount ? 'Last page' : undefined
                                        }
                                        onClick={() => {
                                            pauseFollowing()
                                            setFailurePage(currentFailurePage + 1)
                                        }}
                                    >
                                        Next
                                    </LemonButton>
                                </div>
                            )}
                            {individualRows(
                                additionalFailures.slice(currentFailurePage * 10, (currentFailurePage + 1) * 10)
                            )}
                        </div>
                    </ActivityDisclosure>
                    {rows(window.first)}
                    {window.hiddenCount > 0 && (
                        <>
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                data-attr="thread-activity-more"
                                aria-expanded={showMiddle}
                                aria-controls={`activity-middle-${group.id}`}
                                onClick={() => {
                                    pauseFollowing()
                                    setShowMiddle(!showMiddle)
                                }}
                            >
                                {showMiddle ? 'Hide middle activity' : `Show ${window.hiddenCount} more`}
                            </LemonButton>
                            <ActivityDisclosure open={showMiddle} id={`activity-middle-${group.id}`}>
                                <div className="flex flex-col gap-1 min-w-0">
                                    <div className="flex items-center gap-2 flex-wrap text-muted">
                                        <LemonButton
                                            size="xsmall"
                                            type="tertiary"
                                            disabledReason={window.page === 0 ? 'First page' : undefined}
                                            onClick={() => {
                                                pauseFollowing()
                                                setMiddlePage(window.page - 1)
                                            }}
                                            data-attr="thread-activity-previous"
                                        >
                                            Previous
                                        </LemonButton>
                                        <span>
                                            Page {window.page + 1} of {window.pageCount}
                                        </span>
                                        <LemonButton
                                            size="xsmall"
                                            type="tertiary"
                                            disabledReason={
                                                window.page + 1 === window.pageCount ? 'Last page' : undefined
                                            }
                                            onClick={() => {
                                                pauseFollowing()
                                                setMiddlePage(window.page + 1)
                                            }}
                                            data-attr="thread-activity-next"
                                        >
                                            Next
                                        </LemonButton>
                                    </div>
                                    {rows(window.middle)}
                                </div>
                            </ActivityDisclosure>
                        </>
                    )}
                    {rows(window.last)}
                    {newCount > 0 && (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            data-attr="thread-activity-refresh"
                            onClick={() => setVisibleIds(group.items.map((item) => item.id))}
                        >
                            Show {newCount} new {newCount === 1 ? 'activity' : 'activities'}
                        </LemonButton>
                    )}
                </div>
            </ActivityDisclosure>
        </div>
    )
}
