import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { P, match } from 'ts-pattern'

import { IconLogomark } from '@posthog/icons'
import { LemonCard } from '@posthog/lemon-ui'

import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventType } from 'lib/components/Errors/types'
import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingTrigger from 'lib/components/ViewRecordingButton/ViewRecordingTrigger'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TabsPrimitive, TabsPrimitiveList, TabsPrimitiveTrigger } from 'lib/ui/TabsPrimitive/TabsPrimitive'

import { ErrorTrackingRelationalIssue } from '~/schema'

import { PropertiesTab } from './Tabs/PropertiesTab'
import { StacktraceTab } from './Tabs/StacktraceTab'
import { exceptionCardLogic } from './exceptionCardLogic'

interface ExceptionCardContentProps {
    issue?: ErrorTrackingRelationalIssue
    issueLoading: boolean
    timestamp?: string
    label?: JSX.Element
}

export interface ExceptionCardProps extends Omit<ExceptionCardContentProps, 'timestamp'> {
    event?: ErrorEventType
    eventLoading: boolean
}

export function ExceptionCard({ issue, issueLoading, event, eventLoading }: ExceptionCardProps): JSX.Element {
    const { setLoading } = useActions(exceptionCardLogic)

    useEffect(() => {
        setLoading(eventLoading)
    }, [setLoading, eventLoading])

    return (
        <BindLogic
            logic={errorPropertiesLogic}
            props={
                {
                    properties: event?.properties,
                    id: event?.uuid ?? issue?.id ?? 'error',
                } as ErrorPropertiesLogicProps
            }
        >
            <ExceptionCardContent issue={issue} timestamp={event?.timestamp} issueLoading={issueLoading} />
        </BindLogic>
    )
}

function ExceptionCardContent({ issue, issueLoading, timestamp }: ExceptionCardContentProps): JSX.Element {
    const { sessionId, mightHaveRecording } = useValues(errorPropertiesLogic)

    return (
        <LemonCard hoverEffect={false} className="relative overflow-hidden p-0">
            <TabsPrimitive defaultValue="stacktrace">
                <div className="flex h-[2rem] w-full items-center justify-between border-b px-2">
                    <TabsPrimitiveList className="flex h-full w-full items-center justify-between">
                        <div className="h-full w-full">
                            <div className="flex h-full items-center gap-1 text-lg">
                                <IconLogomark />
                                <span className="text-sm">Exception</span>
                            </div>
                        </div>
                        <div className="flex h-full w-full justify-center gap-2">
                            <TabsPrimitiveTrigger className="px-2" value="stacktrace">
                                Stacktrace
                            </TabsPrimitiveTrigger>
                            <TabsPrimitiveTrigger className="px-2" value="properties">
                                Properties
                            </TabsPrimitiveTrigger>
                        </div>
                        <div className="flex w-full items-center justify-end gap-1">
                            {timestamp && <TZLabel className="text-muted text-xs" time={timestamp} />}
                            <ViewRecordingTrigger sessionId={sessionId} inModal={true} timestamp={timestamp}>
                                {(onClick, _, disabledReason, maybeSpinner) => {
                                    return (
                                        <ButtonPrimitive
                                            disabled={disabledReason != null || !mightHaveRecording}
                                            onClick={onClick}
                                            className="h-[1.4rem] whitespace-nowrap px-2"
                                            tooltip={match([disabledReason != null, mightHaveRecording])
                                                .with([true, P.any], () => 'No recording available')
                                                .with([false, false], () => 'Recording not ready')
                                                .otherwise(() => 'View Recording')}
                                        >
                                            <IconPlayCircle />
                                            Recording
                                            {maybeSpinner}
                                        </ButtonPrimitive>
                                    )
                                }}
                            </ViewRecordingTrigger>
                        </div>
                    </TabsPrimitiveList>
                </div>
                <StacktraceTab value="stacktrace" issue={issue} issueLoading={issueLoading} timestamp={timestamp} />
                <PropertiesTab value="properties" />
            </TabsPrimitive>
        </LemonCard>
    )
}
