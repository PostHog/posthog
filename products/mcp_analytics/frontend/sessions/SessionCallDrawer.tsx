import { useActions, useValues } from 'kea'

import { IconArrowUpRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { ExpandedEventRow } from '~/queries/nodes/DataTable/ExpandedEventRow'

import { MCPDetailDrawer } from '../components/MCPDetailDrawer'
import { sessionCallDrawerLogic } from './sessionCallDrawerLogic'

export function SessionCallDrawer({ stacked = false }: { stacked?: boolean }): JSX.Element | null {
    const { openedCall, position, previousCall, nextCall, event, eventLoading, eventFailed, fullPageHref } =
        useValues(sessionCallDrawerLogic)
    const { stepTo, close, loadEvent } = useActions(sessionCallDrawerLogic)

    if (!openedCall || !fullPageHref) {
        return null
    }
    // A step lands before its event does, so the previous call's event never shows under the new title.
    const loadedEvent = event?.uuid === openedCall.event_id ? event : null

    return (
        <MCPDetailDrawer
            noun="tool call"
            title={<span className="font-mono">{openedCall.tool_name || 'unknown'}</span>}
            position={position}
            onPrevious={previousCall ? () => stepTo('previous') : null}
            onNext={nextCall ? () => stepTo('next') : null}
            fullPageHref={fullPageHref}
            fullPageLabel="View event"
            fullPageIcon={<IconArrowUpRight />}
            onClose={close}
            stacked={stacked}
            data-attr="mcp-session-call-drawer"
        >
            {loadedEvent ? (
                <ExpandedEventRow event={loadedEvent} />
            ) : eventLoading ? (
                <div className="flex flex-col gap-2" aria-busy>
                    <LemonSkeleton className="h-8 w-2/3" />
                    <LemonSkeleton className="h-32" />
                </div>
            ) : eventFailed ? (
                <div className="flex flex-col items-start gap-2 text-sm text-secondary">
                    Could not load this tool call.
                    <LemonButton size="small" type="secondary" onClick={() => loadEvent(openedCall)}>
                        Retry
                    </LemonButton>
                </div>
            ) : (
                <div className="text-sm text-secondary">This tool call is no longer available.</div>
            )}
        </MCPDetailDrawer>
    )
}
