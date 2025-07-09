import { IconLogomark } from '@posthog/icons'
import { LemonCard } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { errorPropertiesLogic, ErrorPropertiesLogicProps } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventType } from 'lib/components/Errors/types'
import { TZLabel } from 'lib/components/TZLabel'
import { TabsPrimitive, TabsPrimitiveList, TabsPrimitiveTrigger } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { useEffect } from 'react'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { exceptionCardLogic } from './exceptionCardLogic'
import { PropertiesTab } from './Tabs/PropertiesTab'
import { StacktraceTab } from './Tabs/StacktraceTab'
import ViewRecordingTrigger from 'lib/components/ViewRecordingButton/ViewRecordingTrigger'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { match, P } from 'ts-pattern'
import { IconPlayCircle } from 'lib/lemon-ui/icons'

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
        <LemonCard hoverEffect={false} className="p-0 relative overflow-hidden">
            <TabsPrimitive defaultValue="stacktrace">
                <div className="flex justify-between h-[2rem] items-center w-full px-2 border-b">
                    <TabsPrimitiveList className="flex justify-between w-full h-full items-center">
                        <div className="w-full h-full">
                            <div className="flex items-center gap-1 text-lg h-full">
                                <IconLogomark />
                                <span className="text-sm">Exception</span>
                            </div>
                        </div>
                        <div className="flex gap-2 w-full justify-center h-full">
                            <TabsPrimitiveTrigger className="px-2" value="stacktrace">
                                Stacktrace
                            </TabsPrimitiveTrigger>
                            <TabsPrimitiveTrigger className="px-2" value="properties">
                                Properties
                            </TabsPrimitiveTrigger>
                        </div>
                        <div className="w-full flex gap-1 justify-end items-center">
                            {timestamp && <TZLabel className="text-muted text-xs" time={timestamp} />}
                            <ViewRecordingTrigger sessionId={sessionId} inModal={true} timestamp={timestamp}>
                                {(onClick, _, disabledReason, maybeSpinner) => {
                                    return (
                                        <ButtonPrimitive
                                            disabled={disabledReason != null || !mightHaveRecording}
                                            onClick={onClick}
                                            className="px-2 h-[1.4rem] whitespace-nowrap"
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
