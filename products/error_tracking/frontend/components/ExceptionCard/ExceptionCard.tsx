import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

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
import { StackTraceTab } from './Tabs/StackTraceTab'
import { exceptionCardLogic } from './exceptionCardLogic'

interface ExceptionCardContentProps {
    timestamp?: string
    label?: JSX.Element

    renderStackTraceActions?: () => JSX.Element | null
}

export interface ExceptionCardProps extends Omit<ExceptionCardContentProps, 'timestamp' | 'issueId'> {
    issueId: ErrorTrackingRelationalIssue['id']
    event?: ErrorEventType
    loading: boolean
}

export function ExceptionCard({ issueId, event, loading, ...contentProps }: ExceptionCardProps): JSX.Element {
    const cardLogicProps = useMemo(() => ({ issueId }), [issueId])
    const { setLoading } = useActions(exceptionCardLogic(cardLogicProps))

    useEffect(() => {
        setLoading(loading)
    }, [setLoading, loading])

    const eventProps = useMemo(
        () =>
            ({
                properties: event?.properties,
                id: event?.uuid ?? issueId ?? 'error',
            }) as ErrorPropertiesLogicProps,
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [event?.uuid ?? issueId]
    )

    return (
        <BindLogic logic={exceptionCardLogic} props={cardLogicProps}>
            <BindLogic logic={errorPropertiesLogic} props={eventProps}>
                <BindLogic logic={releasePreviewLogic} props={eventProps}>
                    <ExceptionCardContent timestamp={event?.timestamp} {...contentProps} />
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

function ExceptionCardContent({ timestamp, renderStackTraceActions, label }: ExceptionCardContentProps): JSX.Element {
    const { currentTab } = useValues(exceptionCardLogic)
    const { setCurrentTab } = useActions(exceptionCardLogic)

    return (
        <LemonCard hoverEffect={false} className="p-0 relative overflow-y-auto w-full border-0 rounded-none">
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
                            <TabsPrimitiveTrigger className="px-2 whitespace-nowrap" value="stack_trace">
                                Stack Trace
                            </TabsPrimitiveTrigger>
                            <TabsPrimitiveTrigger className="px-2 whitespace-nowrap" value="properties">
                                Properties
                            </TabsPrimitiveTrigger>
                            <TabsPrimitiveTrigger className="px-2 whitespace-nowrap" value="session">
                                Session
                            </TabsPrimitiveTrigger>
                        </div>
                        <div className="w-full flex gap-2 justify-end items-center">
                            {timestamp && <TZLabel className="text-muted text-xs" time={timestamp} />}
                            {label}
                        </div>
                    </TabsPrimitiveList>
                </div>
                <StackTraceTab value="stack_trace" renderActions={renderStackTraceActions} />
                <PropertiesTab value="properties" />
                <SessionTab value="session" timestamp={timestamp} />
            </TabsPrimitive>
        </LemonCard>
    )
}
