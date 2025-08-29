import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'
import { P, match } from 'ts-pattern'

import { Spinner } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { SessionTimeline, SessionTimelineHandle } from 'lib/components/SessionTimeline/SessionTimeline'
import { SnapshotLoader } from 'lib/components/SessionTimeline/snapshot-loader'
import { ItemCategory, ItemCollector, ItemLoader, ItemRenderer } from 'lib/components/SessionTimeline/timeline'
import { customItemLoader, customItemRenderer } from 'lib/components/SessionTimeline/timeline/items/custom'
import { exceptionLoader, exceptionRenderer } from 'lib/components/SessionTimeline/timeline/items/exceptions'
import { ConsoleLogItemLoader, consoleLogsRenderer } from 'lib/components/SessionTimeline/timeline/items/log'
import { pageLoader, pageRenderer } from 'lib/components/SessionTimeline/timeline/items/page'
import { Dayjs, dayjs } from 'lib/dayjs'
import {
    TabsPrimitive,
    TabsPrimitiveContent,
    TabsPrimitiveContentProps,
    TabsPrimitiveList,
    TabsPrimitiveTrigger,
} from 'lib/ui/TabsPrimitive/TabsPrimitive'

import { exceptionCardLogic } from '../../exceptionCardLogic'
import { SubHeader } from '../SubHeader'
import { SessionLoading, SessionRecordingTab } from './SessionRecordingTab'
import { sessionTabLogic } from './sessionTabLogic'

export interface SessionTabProps extends TabsPrimitiveContentProps {
    timestamp?: string
}

export function SessionTab({ timestamp, ...props }: SessionTabProps): JSX.Element {
    const { sessionId } = useValues(errorPropertiesLogic)
    const { loading, currentSessionTab } = useValues(exceptionCardLogic)
    const { setCurrentSessionTab } = useActions(exceptionCardLogic)

    return (
        <TabsPrimitiveContent {...props}>
            {match([loading, sessionId])
                .with([true, P.any], () => (
                    <div className="flex justify-center items-center h-[300px]">
                        <Spinner />
                    </div>
                ))
                .with([false, P.nullish], () => <NoSessionIdFound />)
                .with([false, P.string], ([_, sessionId]) => (
                    <BindLogic logic={sessionTabLogic} props={{ timestamp, sessionId }}>
                        <TabsPrimitive value={currentSessionTab} onValueChange={setCurrentSessionTab}>
                            <SubHeader className="p-0">
                                <TabsPrimitiveList className="flex justify-start gap-2 w-full h-full items-center">
                                    <TabsPrimitiveTrigger className="px-2 h-full" value="timeline">
                                        Timeline
                                    </TabsPrimitiveTrigger>
                                    <TabsPrimitiveTrigger className="px-2 h-full" value="recording">
                                        Recording
                                    </TabsPrimitiveTrigger>
                                </TabsPrimitiveList>
                            </SubHeader>
                            <SessionTimelineTab />
                            <SessionRecordingTab />
                        </TabsPrimitive>
                    </BindLogic>
                ))
                .exhaustive()}
        </TabsPrimitiveContent>
    )
}

export function SessionTimelineTab(): JSX.Element {
    const { uuid } = useValues(errorPropertiesLogic)
    const sessionTimelineRef = useRef<SessionTimelineHandle>(null)
    const { currentSessionTab } = useValues(exceptionCardLogic)
    const { sessionId, timestamp } = useValues(sessionTabLogic)
    const { setRecordingTimestamp } = useActions(sessionTabLogic)
    const { setCurrentSessionTab } = useActions(exceptionCardLogic)
    const [collector, setCollector] = useState<ItemCollector | undefined>(undefined)

    const scrollToItem = useCallback(() => {
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

    useEffect(() => {
        if (!sessionId || !timestamp) {
            return undefined
        }
        const timestampDayJs = dayjs(timestamp).add(1, 'millisecond')
        const categories: [ItemCategory, ItemRenderer<any>, ItemLoader<any>][] = [
            [ItemCategory.ERROR_TRACKING, exceptionRenderer, exceptionLoader(sessionId, timestampDayJs)],
            [ItemCategory.PAGE_VIEWS, pageRenderer, pageLoader(sessionId, timestampDayJs)],
            [ItemCategory.CUSTOM_EVENTS, customItemRenderer, customItemLoader(sessionId, timestampDayJs)],
        ]
        SnapshotLoader.build(sessionId, { blob_v2: true, blob_v2_lts: true })
            .then((loader) => {
                // Sources are available
                categories.push([ItemCategory.CONSOLE_LOGS, consoleLogsRenderer, new ConsoleLogItemLoader(loader)])
            })
            .catch(() => {})
            .finally(() => {
                setCollector(new ItemCollector(sessionId, timestampDayJs, categories))
            })
    }, [sessionId, timestamp])

    return (
        <TabsPrimitiveContent value="timeline">
            {collector && (
                <SessionTimeline
                    ref={sessionTimelineRef}
                    collector={collector}
                    selectedItemId={uuid}
                    onTimeClick={onTimeClick}
                    onFirstLoad={scrollToItem}
                />
            )}
            {!collector && <SessionLoading />}
        </TabsPrimitiveContent>
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
