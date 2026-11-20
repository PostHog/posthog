import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowUpRight, IconOpenSidebar } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { ExpandedEventRow } from '~/queries/nodes/DataTable/ExpandedEventRow'

import { MCPDetailDrawer } from '../components/MCPDetailDrawer'
import { SessionDrawer } from '../sessions/SessionDrawer'
import { activityDrawerLogic } from './activityDrawerLogic'

export function ActivityDrawer(): JSX.Element | null {
    const { openedRow, position, previousRow, nextRow, event, loadedEventLoading, eventFailed, fullPageHref } =
        useValues(activityDrawerLogic)
    const { stepTo, close, loadEvent } = useActions(activityDrawerLogic)
    const [sessionOpen, setSessionOpen] = useState(false)
    useEffect(() => setSessionOpen(false), [openedRow])

    if (!openedRow || !fullPageHref) {
        return null
    }

    const { sessionId, timestamp, eventId } = openedRow
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
                    <div className="flex flex-col items-start gap-2">
                        {sessionId ? (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconOpenSidebar />}
                                onClick={() => setSessionOpen(true)}
                                data-attr="mcp-activity-drawer-view-session"
                            >
                                View session
                            </LemonButton>
                        ) : null}
                        <ExpandedEventRow event={event} />
                    </div>
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
            {sessionOpen && sessionId ? (
                <SessionDrawer
                    sessionId={sessionId}
                    timestamp={timestamp}
                    focusedEventId={eventId}
                    stacked
                    onClose={() => setSessionOpen(false)}
                    dataAttr="mcp-activity-session-drawer"
                />
            ) : null}
        </>
    )
}
