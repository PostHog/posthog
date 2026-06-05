import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { IconLogomark } from '@posthog/icons'
import { LemonCard } from '@posthog/lemon-ui'

import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventType } from 'lib/components/Errors/types'
import { TZLabel } from 'lib/components/TZLabel'
import { TabsPrimitive, TabsPrimitiveList, TabsPrimitiveTrigger } from 'lib/ui/TabsPrimitive/TabsPrimitive'

import { releasePreviewLogic } from '../ExceptionAttributesPreview/ReleasesPreview/releasePreviewLogic'
import { exceptionCardLogic } from './exceptionCardLogic'
import { AITraceTab } from './Tabs/AITraceTab'
import { PropertiesTab } from './Tabs/PropertiesTab'
import { SessionTab } from './Tabs/SessionTab'
import { StackTraceTab } from './Tabs/StackTraceTab'

interface ExceptionCardContentProps {
    timestamp?: string
    label?: JSX.Element
    /** Hide timestamp and label from the tab bar (e.g. when shown elsewhere on mobile) */
    hideEventMeta?: boolean

    renderStackTraceActions?: () => JSX.Element | null
    traceId?: string | null
    spanId?: string | null
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
                    <ExceptionCardContent
                        timestamp={event?.timestamp}
                        traceId={getStringProperty(event?.properties?.$ai_trace_id)}
                        spanId={getStringProperty(event?.properties?.$ai_span_id)}
                        {...contentProps}
                    />
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

function ExceptionCardContent({
    timestamp,
    renderStackTraceActions,
    label,
    hideEventMeta,
    traceId,
    spanId,
}: ExceptionCardContentProps): JSX.Element {
    const { currentTab } = useValues(exceptionCardLogic)
    const { setCurrentTab } = useActions(exceptionCardLogic)

    useEffect(() => {
        if (currentTab === 'ai_trace' && !traceId) {
            setCurrentTab('stack_trace')
        }
    }, [currentTab, setCurrentTab, traceId])

    return (
        <LemonCard hoverEffect={false} className="p-0 relative w-full h-full border-0 rounded-none flex flex-col">
            <TabsPrimitive value={currentTab} onValueChange={setCurrentTab} className="flex flex-col flex-1 min-h-0">
                <div className="flex justify-between h-[2rem] items-center w-full px-2 border-b shrink-0">
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
                            {traceId ? (
                                <TabsPrimitiveTrigger className="px-2 whitespace-nowrap" value="ai_trace">
                                    AI trace
                                </TabsPrimitiveTrigger>
                            ) : null}
                        </div>
                        <div className="w-full flex gap-2 justify-end items-center">
                            {!hideEventMeta && timestamp && <TZLabel className="text-muted text-xs" time={timestamp} />}
                            {!hideEventMeta && label}
                        </div>
                    </TabsPrimitiveList>
                </div>
                <StackTraceTab value="stack_trace" renderActions={renderStackTraceActions} className="flex-1 min-h-0" />
                <PropertiesTab value="properties" className="flex-1 min-h-0" />
                <SessionTab value="session" timestamp={timestamp} className="flex-1 min-h-0" />
                {traceId ? (
                    <AITraceTab
                        value="ai_trace"
                        traceId={traceId}
                        spanId={spanId}
                        timestamp={timestamp}
                        className="flex-1 min-h-0"
                    />
                ) : null}
            </TabsPrimitive>
        </LemonCard>
    )
}

function getStringProperty(value: unknown): string | null {
    return typeof value === 'string' && value.length > 0 ? value : null
}
