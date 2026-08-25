import { BindLogic, useActions, useValues } from 'kea'
import { useMemo, type CSSProperties } from 'react'

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
                <div className="grid h-10 w-full shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-2 border-b px-2">
                    <div className="flex h-full min-w-0 items-center gap-1 text-lg">
                        <IconLogomark />
                        <span className="text-sm">Exception</span>
                    </div>
                    <TabsList variant="line" aria-label="Exception details" className="h-full! self-stretch">
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
                <StackTraceTab value="stack_trace" renderActions={renderStackTraceActions} className="flex-1 min-h-0" />
                <PropertiesTab value="properties" className="flex-1 min-h-0" />
                <SessionTab timestamp={timestamp} eventMarkerColor={eventMarkerColor} />
                <ExceptionCardFooter eventId={eventId} fingerprint={fingerprint} label={label} timestamp={timestamp} />
            </Tabs>
        </LemonCard>
    )
}
