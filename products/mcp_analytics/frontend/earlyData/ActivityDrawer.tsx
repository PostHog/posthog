import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowUpRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { MCPDetailDrawer } from '../components/MCPDetailDrawer'
import { ToolCallEventView } from '../components/ToolCallEventView'
import { SessionCallDrawer } from '../sessions/SessionCallDrawer'
import { sessionCallDrawerLogic } from '../sessions/sessionCallDrawerLogic'
import { activityDrawerLogic } from './activityDrawerLogic'

export function ActivityDrawer(): JSX.Element | null {
    const { openedRow, position, previousRow, nextRow, event, loadedEventLoading, eventFailed, fullPageHref } =
        useValues(activityDrawerLogic)
    const { stepTo, close, loadEvent } = useActions(activityDrawerLogic)
    const { close: closeCallDrawer } = useActions(sessionCallDrawerLogic)
    // A call opened from another row's session would sit over the wrong call.
    useEffect(() => closeCallDrawer, [openedRow, closeCallDrawer])

    if (!openedRow || !fullPageHref) {
        return null
    }

    const toolName = event?.properties?.$mcp_tool_name

    return (
        <>
            <MCPDetailDrawer
                noun="tool call"
                title={toolName ? <span className="font-mono">{String(toolName)}</span> : null}
                position={position}
                onPrevious={previousRow ? () => stepTo('previous') : null}
                onNext={nextRow ? () => stepTo('next') : null}
                fullPageHref={fullPageHref}
                fullPageLabel="View event"
                fullPageIcon={<IconArrowUpRight />}
                onClose={close}
                data-attr="mcp-activity-drawer"
            >
                {event ? (
                    <ToolCallEventView event={event} showSession />
                ) : loadedEventLoading ? (
                    <div className="flex flex-col gap-2" aria-busy>
                        <LemonSkeleton className="h-8 w-2/3" />
                        <LemonSkeleton className="h-32" />
                    </div>
                ) : eventFailed ? (
                    <div className="flex flex-col items-start gap-2 text-sm text-secondary">
                        Could not load this tool call.
                        <LemonButton size="small" type="secondary" onClick={() => loadEvent(openedRow)}>
                            Retry
                        </LemonButton>
                    </div>
                ) : (
                    <div className="text-sm text-secondary">This tool call is no longer available.</div>
                )}
            </MCPDetailDrawer>
            <SessionCallDrawer stacked />
        </>
    )
}
