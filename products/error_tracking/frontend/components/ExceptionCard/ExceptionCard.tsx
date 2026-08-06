import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { IconLogomark } from '@posthog/icons'

import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventType } from 'lib/components/Errors/types'
import { TZLabel } from 'lib/components/TZLabel'
import { Tabs, TabsList, TabsTrigger } from 'lib/ui/quill'

import { releasePreviewLogic } from '../ExceptionAttributesPreview/ReleasesPreview/releasePreviewLogic'
import { exceptionCardLogic } from './exceptionCardLogic'
import { PropertiesTab } from './Tabs/PropertiesTab'
import { SessionTab } from './Tabs/SessionTab'
import { StackTraceTab } from './Tabs/StackTraceTab'

interface ExceptionCardContentProps {
    timestamp?: string
    label?: JSX.Element
    /** Hide timestamp and label from the tab bar (e.g. when shown elsewhere on mobile) */
    hideEventMeta?: boolean

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
                timestamp: event?.timestamp,
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

function ExceptionCardContent({
    timestamp,
    renderStackTraceActions,
    label,
    hideEventMeta,
}: ExceptionCardContentProps): JSX.Element {
    const { currentTab } = useValues(exceptionCardLogic)
    const { setCurrentTab } = useActions(exceptionCardLogic)

    return (
        <div data-quill className="relative flex h-full w-full flex-col bg-[var(--card)]">
            <Tabs value={currentTab} onValueChange={setCurrentTab} className="min-h-0 flex-1 gap-0">
                <div className="flex h-9 w-full shrink-0 items-center justify-between border-b border-border px-2">
                    <TabsList variant="line" className="flex h-full w-full items-center justify-between p-0">
                        <div className="w-full h-full">
                            <div className="flex items-center gap-1 text-lg h-full">
                                <IconLogomark />
                                <span className="text-sm">Exception</span>
                            </div>
                        </div>
                        <div className="flex h-full w-full items-center justify-center gap-2">
                            <TabsTrigger className="h-auto flex-none px-2 whitespace-nowrap" value="stack_trace">
                                Stack Trace
                            </TabsTrigger>
                            <TabsTrigger className="h-auto flex-none px-2 whitespace-nowrap" value="properties">
                                Properties
                            </TabsTrigger>
                            <TabsTrigger className="h-auto flex-none px-2 whitespace-nowrap" value="session">
                                Session
                            </TabsTrigger>
                        </div>
                        <div className="w-full flex gap-2 justify-end items-center">
                            {!hideEventMeta && timestamp && (
                                <span className="contents">
                                    <TZLabel className="text-xs text-muted-foreground" time={timestamp} />
                                </span>
                            )}
                            {!hideEventMeta && label}
                        </div>
                    </TabsList>
                </div>
                <StackTraceTab value="stack_trace" renderActions={renderStackTraceActions} className="flex-1 min-h-0" />
                <PropertiesTab value="properties" className="flex-1 min-h-0" />
                <SessionTab value="session" timestamp={timestamp} className="flex-1 min-h-0" />
            </Tabs>
        </div>
    )
}
