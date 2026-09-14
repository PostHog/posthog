import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, type CSSProperties } from 'react'

import { IconLogomark } from '@posthog/icons'
import { LemonCard } from '@posthog/lemon-ui'

import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventType } from 'lib/components/Errors/types'
import type { TimelineMarkerColor } from 'lib/components/SessionTimeline/SessionTimeline'
import { Tabs, TabsList, TabsTrigger } from 'lib/ui/quill'

import { ViewLogsButton } from 'products/logs/frontend/components/ViewLogsButton'

import { ExceptionCardFooter } from './ExceptionCardFooter'
import { exceptionCardLogic } from './exceptionCardLogic'
import { PropertiesTab } from './Tabs/PropertiesTab'
import { SessionTab } from './Tabs/SessionTab'
import { StackTraceTab } from './Tabs/StackTraceTab'

interface ExceptionCardContentProps {
    eventId?: string
    fingerprint?: string
    timestamp?: string
    eventMarkerColor?: TimelineMarkerColor
    label?: JSX.Element

    renderStackTraceActions?: () => JSX.Element | null
}

export interface ExceptionCardProps extends ExceptionCardContentProps {
    issueId: string
    issueName: string | null
    event?: ErrorEventType
    loading: boolean
}

export function ExceptionCard({
    issueId,
    issueName,
    event,
    loading,
    ...contentProps
}: ExceptionCardProps): JSX.Element {
    const cardLogicProps = useMemo(() => ({ issueId, loading }), [issueId, loading])

    const eventProps = useMemo<ErrorPropertiesLogicProps>(
        () => ({
            properties: event?.properties,
            id: event?.uuid ?? issueId,
            timestamp: event?.timestamp,
        }),
        [event?.properties, event?.timestamp, event?.uuid, issueId]
    )
    const fingerprint = event?.properties?.$exception_fingerprint

    return (
        <BindLogic logic={exceptionCardLogic} props={cardLogicProps}>
            <BindLogic logic={errorPropertiesLogic} props={eventProps}>
                <ExceptionCardContent
                    eventId={event?.uuid}
                    fingerprint={typeof fingerprint === 'string' ? fingerprint : undefined}
                    timestamp={event?.timestamp}
                    {...contentProps}
                />
            </BindLogic>
        </BindLogic>
    )
}

function ExceptionCardContent({
    eventId,
    fingerprint,
    timestamp,
    eventMarkerColor,
    renderStackTraceActions,
    label,
}: ExceptionCardContentProps): JSX.Element {
    const { currentTab } = useValues(exceptionCardLogic)
    const { sessionId } = useValues(errorPropertiesLogic)
    const { setCurrentTab } = useActions(exceptionCardLogic)
    const headerRef = useRef<HTMLDivElement>(null)

    // Base UI scrolls the active tab into view on mount and on keyboard navigation, but not when the
    // value changes from elsewhere. The timeline switches to the recording tab on a timestamp click, so
    // in a narrow pane the active tab can sit outside the scroller with no scrollbar to reveal it.
    // Nudging scrollLeft rather than calling scrollIntoView keeps ancestors — the page — where they are.
    useEffect(() => {
        const list = headerRef.current?.querySelector<HTMLElement>('[data-slot="tabs-list"]')
        const active = list?.querySelector<HTMLElement>('[data-active]')
        if (!list || !active) {
            return
        }
        const clippedLeft = active.offsetLeft - list.scrollLeft
        const clippedRight = active.offsetLeft + active.offsetWidth - (list.scrollLeft + list.clientWidth)
        if (clippedLeft < 0) {
            list.scrollLeft += clippedLeft
        } else if (clippedRight > 0) {
            list.scrollLeft += clippedRight
        }
    }, [currentTab])

    return (
        <LemonCard hoverEffect={false} className="p-0 relative w-full h-full border-0 rounded-none flex flex-col">
            <Tabs
                value={currentTab}
                onValueChange={(value) => {
                    if (
                        value === 'stack_trace' ||
                        value === 'properties' ||
                        value === 'timeline' ||
                        value === 'recording'
                    ) {
                        setCurrentTab(value)
                    }
                }}
                className="flex min-h-0 flex-1 flex-col gap-0"
            >
                {/* Container query, not viewport: the card sits in a resizable split pane. At @xl and up,
                    symmetric 1fr gutters centre the tab bar; below it the gutters shrink to their content
                    so the tab bar keeps the slack. The container wraps the header alone — inline-size
                    containment zeroes an element's intrinsic width contribution, and on the card as a
                    whole that collapses it to nothing inside a shrink-to-fit parent. */}
                <div className="@container/exception-card shrink-0">
                    <div
                        ref={headerRef}
                        className="grid h-10 w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 border-b px-2 @xl/exception-card:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]"
                    >
                        {/* min-w-0 lets this track collapse, so the cell must clip: an unclipped label draws
                        over the tab bar. */}
                        <div className="flex h-full min-w-0 items-center gap-1 overflow-hidden text-lg">
                            <IconLogomark className="shrink-0" />
                            {/* sr-only rather than hidden: no room to draw it, but it stays in the a11y tree. */}
                            <span className="truncate text-sm @max-xl/exception-card:sr-only">Exception</span>
                        </div>
                        {/* Under ~390px the tab bar alone does not fit, so it scrolls. justify-start overrides
                        the list's own justify-center: a centred flex row that overflows spills off *both*
                        edges, which puts the first tab out of reach of the scroller. */}
                        <TabsList
                            variant="line"
                            aria-label="Exception details"
                            className="h-full! max-w-full justify-start self-stretch overflow-x-auto hide-scrollbar"
                        >
                            <TabsTrigger
                                value="stack_trace"
                                className="text-sm"
                                style={{ '--background': 'transparent' } as CSSProperties}
                            >
                                Stack Trace
                            </TabsTrigger>
                            <TabsTrigger
                                value="properties"
                                className="text-sm"
                                style={{ '--background': 'transparent' } as CSSProperties}
                            >
                                Properties
                            </TabsTrigger>
                            <TabsTrigger
                                value="timeline"
                                className="text-sm"
                                style={{ '--background': 'transparent' } as CSSProperties}
                            >
                                Timeline
                            </TabsTrigger>
                            <TabsTrigger
                                value="recording"
                                className="text-sm"
                                style={{ '--background': 'transparent' } as CSSProperties}
                            >
                                Recording
                            </TabsTrigger>
                        </TabsList>
                        <div className="flex justify-end">
                            {sessionId && (currentTab === 'timeline' || currentTab === 'recording') ? (
                                <ViewLogsButton
                                    sessionId={sessionId}
                                    timestamp={timestamp}
                                    size="xsmall"
                                    data-attr="error-tracking-session-view-logs"
                                />
                            ) : null}
                        </div>
                    </div>
                </div>
                <StackTraceTab value="stack_trace" renderActions={renderStackTraceActions} className="flex-1 min-h-0" />
                <PropertiesTab value="properties" className="flex-1 min-h-0" />
                <SessionTab timestamp={timestamp} eventMarkerColor={eventMarkerColor} />
                <ExceptionCardFooter eventId={eventId} fingerprint={fingerprint} label={label} timestamp={timestamp} />
            </Tabs>
        </LemonCard>
    )
}
