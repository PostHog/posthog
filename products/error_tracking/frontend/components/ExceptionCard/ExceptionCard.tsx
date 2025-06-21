import { IconLogomark } from '@posthog/icons'
import { LemonCard } from '@posthog/lemon-ui'
import { BindLogic, useActions } from 'kea'
import { errorPropertiesLogic, ErrorPropertiesLogicProps } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventType } from 'lib/components/Errors/types'
import { TZLabel } from 'lib/components/TZLabel'
import { TabsPrimitive, TabsPrimitiveList, TabsPrimitiveTrigger } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { useEffect } from 'react'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { exceptionCardLogic } from './exceptionCardLogic'
import { PropertiesTab } from './Tabs/PropertiesTab'
import { RawTab } from './Tabs/RawTab'
import { StacktraceTab } from './Tabs/StacktraceTab'

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

export function ExceptionCard({ issue, issueLoading, label, event, eventLoading }: ExceptionCardProps): JSX.Element {
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
                    timestamp: event?.timestamp,
                    id: issue?.id ?? 'error',
                } as ErrorPropertiesLogicProps
            }
        >
            <ExceptionCardContent
                issue={issue}
                label={label}
                timestamp={event?.timestamp}
                issueLoading={issueLoading}
            />
        </BindLogic>
    )
}

function ExceptionCardContent({ issue, issueLoading, timestamp, label }: ExceptionCardContentProps): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="group p-0 relative overflow-hidden">
            <TabsPrimitive defaultValue="stacktrace">
                <div className="flex justify-between h-[2rem] items-center w-full px-2 border-b">
                    <TabsPrimitiveList className="flex justify-between w-full h-full items-center">
                        <div className="w-full h-full">
                            <TabsPrimitiveTrigger value="raw" className="flex items-center gap-1 text-lg h-full">
                                <IconLogomark />
                                <span className="text-sm">Exception</span>
                            </TabsPrimitiveTrigger>
                        </div>
                        <div className="flex gap-2 w-full justify-center h-full">
                            <TabsPrimitiveTrigger className="px-2" value="stacktrace">
                                Stacktrace
                            </TabsPrimitiveTrigger>
                            <TabsPrimitiveTrigger className="px-2" value="properties">
                                Properties
                            </TabsPrimitiveTrigger>
                        </div>
                        <div className="w-full flex gap-2 justify-end items-center">
                            {timestamp && <TZLabel className="text-muted text-xs" time={timestamp} />}
                            {label}
                        </div>
                    </TabsPrimitiveList>
                </div>
                <StacktraceTab value="stacktrace" issue={issue} issueLoading={issueLoading} timestamp={timestamp} />
                <PropertiesTab value="properties" />
                <RawTab value="raw" />
            </TabsPrimitive>
        </LemonCard>
    )
}
