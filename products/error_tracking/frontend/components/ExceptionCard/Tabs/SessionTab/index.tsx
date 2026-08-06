import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, type ComponentProps } from 'react'
import { P, match } from 'ts-pattern'

import { LemonBanner, Link, Spinner } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventProperties } from 'lib/components/Errors/types'
import { SessionTimeline, SessionTimelineHandle } from 'lib/components/SessionTimeline/SessionTimeline'
import { ItemCategory, ItemCollector } from 'lib/components/SessionTimeline/timeline'
import { CombinedEventLoader } from 'lib/components/SessionTimeline/timeline/items/combined'
import { customItemRenderer } from 'lib/components/SessionTimeline/timeline/items/custom'
import { exceptionRenderer, StaticExceptionLoader } from 'lib/components/SessionTimeline/timeline/items/exceptions'
import {
    ExceptionStepLoader,
    exceptionStepRenderer,
} from 'lib/components/SessionTimeline/timeline/items/exceptionSteps'
import { ConsoleLogLoader, consoleLogRenderer } from 'lib/components/SessionTimeline/timeline/items/logs'
import { pageRenderer } from 'lib/components/SessionTimeline/timeline/items/page'
import { Dayjs, dayjs } from 'lib/dayjs'
import { Tabs, TabsContent, TabsList, TabsTrigger } from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'

import { ViewLogsButton } from 'products/logs/frontend/components/ViewLogsButton'

import { exceptionCardLogic } from '../../exceptionCardLogic'
import { SubHeader } from '../SubHeader'
import { SessionRecordingTab } from './SessionRecordingTab'
import { sessionTabLogic } from './sessionTabLogic'

export interface SessionTabProps extends ComponentProps<typeof TabsContent> {
    timestamp?: string
}

export function SessionTab({ timestamp, className, ...props }: SessionTabProps): JSX.Element {
    const { sessionId } = useValues(errorPropertiesLogic)
    const { loading, currentSessionTab } = useValues(exceptionCardLogic)
    const { setCurrentSessionTab } = useActions(exceptionCardLogic)

    return (
        <TabsContent {...props} className={cn('flex min-w-0 flex-col overflow-hidden', className)}>
            {match([loading, sessionId])
                .with([true, P.any], () => (
                    <div className="flex justify-center items-center h-[300px]">
                        <Spinner />
                    </div>
                ))
                .with([false, P.nullish], () => <NoSessionStepsView timestamp={timestamp} />)
                .with([false, P.string], ([_, sessionId]) => (
                    <BindLogic logic={sessionTabLogic} props={{ timestamp, sessionId }}>
                        <Tabs
                            value={currentSessionTab}
                            onValueChange={setCurrentSessionTab}
                            className="min-h-0 min-w-0 flex-1 gap-0"
                        >
                            <SubHeader className="p-0 shrink-0">
                                <TabsList
                                    variant="line"
                                    className="flex h-full w-full items-center justify-start gap-2 p-0 pl-1"
                                >
                                    <TabsTrigger className="h-auto flex-none px-2" value="timeline">
                                        Timeline
                                    </TabsTrigger>
                                    <TabsTrigger className="h-auto flex-none px-2" value="recording">
                                        Recording
                                    </TabsTrigger>
                                    <div className="ml-auto pr-1">
                                        <ViewLogsButton
                                            sessionId={sessionId}
                                            timestamp={timestamp}
                                            size="xsmall"
                                            data-attr="error-tracking-session-view-logs"
                                        />
                                    </div>
                                </TabsList>
                            </SubHeader>
                            <SessionTimelineTab />
                            <SessionRecordingTab />
                        </Tabs>
                    </BindLogic>
                ))
                .exhaustive()}
        </TabsContent>
    )
}

export function SessionTimelineTab(): JSX.Element {
    const { properties, uuid } = useValues(errorPropertiesLogic)
    const sessionTimelineRef = useRef<SessionTimelineHandle>(null)
    const { currentSessionTab } = useValues(exceptionCardLogic)
    const { sessionId, timestamp } = useValues(sessionTabLogic)
    const { setRecordingTimestamp } = useActions(sessionTabLogic)
    const { setCurrentSessionTab } = useActions(exceptionCardLogic)

    useEffect(() => {
        if (currentSessionTab == 'timeline' && sessionTimelineRef.current) {
            sessionTimelineRef.current.scrollToItem(uuid)
        }
    }, [currentSessionTab, uuid])

    const onTimeClick = useCallback(
        (time: Dayjs) => {
            setRecordingTimestamp(time, 1000)
            setCurrentSessionTab('recording')
        },
        [setRecordingTimestamp, setCurrentSessionTab]
    )

    const collector = useMemo<ItemCollector | undefined>(() => {
        if (!sessionId || !timestamp) {
            return undefined
        }
        return buildSessionCollector({ sessionId, timestamp, exceptionUuid: uuid, properties })
    }, [properties, sessionId, timestamp, uuid])

    return (
        <TabsContent value="timeline" className="min-h-0 min-w-0 flex-1 overflow-y-auto">
            {collector && (
                <div className="contents">
                    <SessionTimeline
                        ref={sessionTimelineRef}
                        collector={collector}
                        selectedItemId={uuid}
                        onTimeClick={onTimeClick}
                    />
                </div>
            )}
        </TabsContent>
    )
}

function NoSessionStepsView({ timestamp }: { timestamp?: string }): JSX.Element {
    const { properties, uuid } = useValues(errorPropertiesLogic)
    const hasSteps = Array.isArray(properties?.$exception_steps) && properties.$exception_steps.length > 0

    const collector = useMemo<ItemCollector | undefined>(() => {
        if (!hasSteps || !timestamp) {
            return undefined
        }
        return buildNoSessionCollector({ timestamp, exceptionUuid: uuid, properties })
    }, [hasSteps, timestamp, uuid, properties])

    if (!collector) {
        return <NoSessionIdFound />
    }

    return (
        <div className="flex flex-col flex-1 min-h-0">
            <LemonBanner type="info" className="m-2 shrink-0">
                No session ID associated with this exception — showing exception steps only.{' '}
                <Link to="https://posthog.com/docs/data/sessions#server-sdks-and-sessions" target="_blank">
                    Learn how to add session tracking →
                </Link>
            </LemonBanner>
            <div className="flex-1 min-h-0 overflow-y-auto">
                <SessionTimeline collector={collector} selectedItemId={uuid} />
            </div>
        </div>
    )
}

export function NoSessionIdFound(): JSX.Element {
    return (
        <div className="flex justify-center w-full h-[300px] items-center">
            <EmptyMessage
                title="No session found"
                description="There is no $session_id associated with this exception. If it was captured from a server SDK, you can read our doc on how to forward session IDs"
                buttonText="Check doc"
                buttonTo="https://posthog.com/docs/data/sessions#server-sdks-and-sessions"
                size="small"
            />
        </div>
    )
}

function buildSessionCollector({
    sessionId,
    timestamp,
    exceptionUuid,
    properties,
}: {
    sessionId: string
    timestamp: string
    exceptionUuid: string
    properties?: ErrorEventProperties
}): ItemCollector {
    const timestampDayJs = dayjs(timestamp).add(1, 'millisecond')
    const collector = new ItemCollector(sessionId, timestampDayJs)

    // Exception steps (in-memory, no API calls)
    if (Array.isArray(properties?.$exception_steps)) {
        collector.addCategory(
            ItemCategory.EXCEPTION_STEPS,
            exceptionStepRenderer,
            new ExceptionStepLoader(exceptionUuid, properties)
        )
    }

    // All event-based categories in a single query
    const eventLoader = new CombinedEventLoader(sessionId, timestampDayJs)
    collector.addCategory(ItemCategory.ERROR_TRACKING, exceptionRenderer, eventLoader)
    collector.addCategory(ItemCategory.PAGE_VIEWS, pageRenderer, eventLoader)
    collector.addCategory(ItemCategory.CUSTOM_EVENTS, customItemRenderer, eventLoader)

    // Console logs (separate table)
    collector.addCategory(
        ItemCategory.CONSOLE_LOGS,
        consoleLogRenderer,
        new ConsoleLogLoader(sessionId, timestampDayJs)
    )

    return collector
}

function buildNoSessionCollector({
    timestamp,
    exceptionUuid,
    properties,
}: {
    timestamp: string
    exceptionUuid: string
    properties?: ErrorEventProperties
}): ItemCollector {
    const collector = new ItemCollector(exceptionUuid, dayjs(timestamp).add(1, 'millisecond'))

    // Current exception as a static item
    collector.addCategory(
        ItemCategory.ERROR_TRACKING,
        exceptionRenderer,
        new StaticExceptionLoader(exceptionUuid, dayjs.utc(timestamp), properties)
    )

    // Exception steps (in-memory)
    collector.addCategory(
        ItemCategory.EXCEPTION_STEPS,
        exceptionStepRenderer,
        new ExceptionStepLoader(exceptionUuid, properties)
    )

    return collector
}
