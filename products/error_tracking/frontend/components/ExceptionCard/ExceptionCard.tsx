
import { IconLogomark, IconMagicWand } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { errorPropertiesLogic, ErrorPropertiesLogicProps } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventType } from 'lib/components/Errors/types'
import { ErrorTrackingException } from 'lib/components/Errors/types'
import { TZLabel } from 'lib/components/TZLabel'
import { TabsPrimitive, TabsPrimitiveList, TabsPrimitiveTrigger } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { useEffect } from 'react'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { exceptionCardLogic } from './exceptionCardLogic'

import { FixModal } from './FixModal'
import { StacktraceBaseDisplayProps, StacktraceEmptyDisplay } from './Stacktrace/StacktraceBase'
import { StacktraceGenericDisplay } from './Stacktrace/StacktraceGenericDisplay'
import { StacktraceJsonDisplay } from './Stacktrace/StacktraceJsonDisplay'
import { StacktraceTextDisplay } from './Stacktrace/StacktraceTextDisplay'

import { PropertiesTab } from './Tabs/PropertiesTab'
import { RawTab } from './Tabs/RawTab'
import { StacktraceTab } from './Tabs/StacktraceTab'


// Helper function to check if any exception has resolved stack frames
function hasResolvedStackFrames(exceptionList: ErrorTrackingException[]): boolean {
    return exceptionList.some((exception) => {
        if (exception.stacktrace?.type === 'resolved' && exception.stacktrace?.frames) {
            return exception.stacktrace.frames.some((frame) => frame.resolved)
        }
        return false
    })
}

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
    const { loading, showContext, isExpanded, showFixModal } = useValues(exceptionCardLogic)
    const { setShowFixModal } = useActions(exceptionCardLogic)
    const { properties, exceptionAttributes, additionalProperties, sessionId, exceptionList } =
        useValues(errorPropertiesLogic)
    const showFixButton = hasResolvedStackFrames(exceptionList)
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
                            {showFixButton && (
                                <LemonButton
                                    icon={<IconMagicWand />}
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() => setShowFixModal(true)}
                                    tooltip="Generate AI prompt to fix this error"
                                >
                                    Fix
                                </LemonButton>
                            )}
                            {label}
                        </div>
                    </TabsPrimitiveList>
                </div>
                <StacktraceTab value="stacktrace" issue={issue} issueLoading={issueLoading} />
                <PropertiesTab value="properties" />
                <RawTab value="raw" />

            </TabsPrimitive>
            <FixModal isOpen={showFixModal} onClose={() => setShowFixModal(false)} />
        </LemonCard>
    )
}
