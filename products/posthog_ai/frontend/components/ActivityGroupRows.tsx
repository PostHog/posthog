import { Fragment, type ReactNode } from 'react'

import { MarkdownMessage } from '../messages/MarkdownMessage'
import type { ThreadItem, ToolInvocation } from '../types/streamTypes'
import { ACTIVITY_CHAIN_MIN, groupConsecutiveTools } from '../utils/groupThreadActivity'
import { resolveToolCall } from '../utils/toolResolver'
import { Activity } from './ActivityPrimitives'
import { lookupToolRenderer } from './tool/toolRegistry'

/**
 * The rows an open activity group lists. With `fold`, a run of identical consecutive calls collapses into
 * one row; the first and last rows of a group never fold, so a reader never opens two accordions to reach
 * one call. Flat rows keep their own item keys, so a row's expanded state survives when the window shifts.
 */
export function ActivityGroupRows({
    items,
    fold,
    thoughtsOnly,
    toolInvocations,
    active,
    renderItem,
}: {
    items: ThreadItem[]
    fold: boolean
    thoughtsOnly: boolean
    toolInvocations: Map<string, ToolInvocation>
    active: boolean
    renderItem: (item: ThreadItem) => ReactNode
}): JSX.Element {
    const individualRows = (rows: ThreadItem[]): ReactNode[] =>
        rows.map((item) => (
            <Fragment key={item.id}>
                {thoughtsOnly ? (
                    <div className="text-muted">
                        <MarkdownMessage id={item.id} content={item.text ?? ''} />
                    </div>
                ) : (
                    renderItem(item)
                )}
            </Fragment>
        ))
    return (
        <>
            {groupConsecutiveTools(items, toolInvocations).flatMap((chain) => {
                if (!fold || chain.length < ACTIVITY_CHAIN_MIN) {
                    return individualRows(chain)
                }
                const chainCalls = chain.map((item) => toolInvocations.get(item.toolCallId!)!)
                const resolved = resolveToolCall(chainCalls[0])
                const entry = lookupToolRenderer(resolved.resolvedKey, !!resolved.innerToolName)
                const failed = chainCalls.filter((call) => call.status === 'failed').length
                const running =
                    active && chainCalls.some((call) => call.status === 'pending' || call.status === 'in_progress')
                return (
                    <div key={chain[0].id} data-attr="thread-tool-chain">
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
            })}
        </>
    )
}
