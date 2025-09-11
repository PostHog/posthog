import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconLogomark } from '@posthog/icons'
import { LemonCard } from '@posthog/lemon-ui'

import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventType } from 'lib/components/Errors/types'
import { TZLabel } from 'lib/components/TZLabel'
import { TabsPrimitive, TabsPrimitiveList, TabsPrimitiveTrigger } from 'lib/ui/TabsPrimitive/TabsPrimitive'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { releasePreviewLogic } from '../ExceptionAttributesPreview/ReleasesPreview/releasePreviewLogic'
import { PropertiesTab } from './Tabs/PropertiesTab'
import { SessionTab } from './Tabs/SessionTab'
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

export function ExceptionCard({ issue, issueLoading, event, eventLoading, label }: ExceptionCardProps): JSX.Element {
    const { setLoading } = useActions(exceptionCardLogic)

    useEffect(() => {
        setLoading(eventLoading)
    }, [setLoading, eventLoading])

    const props = {
        properties: event?.properties,
        id: event?.uuid ?? issue?.id ?? 'error',
    } as ErrorPropertiesLogicProps

    return (
        <BindLogic logic={errorPropertiesLogic} props={props}>
            <BindLogic logic={releasePreviewLogic} props={props}>
                <ExceptionCardContent
                    issue={issue}
                    timestamp={event?.timestamp}
                    issueLoading={issueLoading}
                    label={label}
                />
            </BindLogic>
        </BindLogic>
    )
}

function ExceptionCardContent({ issue, issueLoading, timestamp, label }: ExceptionCardContentProps): JSX.Element {
    const { currentTab } = useValues(exceptionCardLogic)
    const { setCurrentTab } = useActions(exceptionCardLogic)

    return (
        <LemonCard hoverEffect={false} className="p-0 relative overflow-hidden">
            <TabsPrimitive value={currentTab} onValueChange={setCurrentTab}>
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
                            <TabsPrimitiveTrigger className="px-2" value="session">
                                Session
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
                <SessionTab value="session" timestamp={timestamp} />
            </TabsPrimitive>
        </LemonCard>
    )
}
