import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { JSONViewer } from 'lib/components/JSONViewer'
import { dayjs } from 'lib/dayjs'
import { TabsPrimitiveContent } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import type { TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { cn } from 'lib/utils/css-classes'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { urls } from 'scenes/urls'

import { useAttachedLogic } from '~/lib/logic/scenes/useAttachedLogic'
import { NodeKind } from '~/queries/schema/schema-general'
import type { DataTableNode, LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { aiObservabilityTraceDataLogic } from 'products/ai_observability/frontend/aiObservabilityTraceDataLogic'
import { aiObservabilityTraceLogic } from 'products/ai_observability/frontend/aiObservabilityTraceLogic'
import {
    EventContentDisplayAsync,
    EventContentGeneration,
} from 'products/ai_observability/frontend/components/EventContentWithAsyncData'
import { JSONValueDisplay } from 'products/ai_observability/frontend/components/JSONValueDisplay'
import { LLMInputOutput } from 'products/ai_observability/frontend/LLMInputOutput'
import { formatLLMEventTitle, isLLMEvent } from 'products/ai_observability/frontend/utils'

const EXCEPTION_LOOKUP_WINDOW_MINUTES = 20

export interface AITraceTabProps extends TabsPrimitiveContentProps {
    traceId: string
    spanId?: string | null
    timestamp?: string
}

export function AITraceTab({ traceId, spanId, timestamp, className, ...props }: AITraceTabProps): JSX.Element {
    const tabId = useMemo(() => `error-tracking-${traceId}`, [traceId])

    return (
        <TabsPrimitiveContent {...props} className={cn('flex flex-col', className)}>
            <BindLogic logic={aiObservabilityTraceLogic} props={{ tabId }}>
                <AITraceTabContent traceId={traceId} spanId={spanId} timestamp={timestamp} tabId={tabId} />
            </BindLogic>
        </TabsPrimitiveContent>
    )
}

function AITraceTabContent({
    traceId,
    spanId,
    timestamp,
    tabId,
}: {
    traceId: string
    spanId?: string | null
    timestamp?: string
    tabId: string
}): JSX.Element {
    const traceLogic = aiObservabilityTraceLogic({ tabId })
    const { searchQuery } = useValues(traceLogic)
    const { setEventId, setTraceId } = useActions(traceLogic)
    const query = useMemo(() => buildInlineTraceQuery(traceId, timestamp), [timestamp, traceId])
    const logicProps = { traceId, query, cachedResults: null, searchQuery, tabId }
    const traceDataLogic = aiObservabilityTraceDataLogic(logicProps)

    useAttachedLogic(traceDataLogic, traceLogic)

    useEffect(() => {
        setTraceId(traceId)
        setEventId(spanId ?? null)
    }, [setEventId, setTraceId, spanId, traceId])

    return (
        <BindLogic logic={aiObservabilityTraceDataLogic} props={logicProps}>
            <AITraceTabInner traceId={traceId} spanId={spanId} timestamp={timestamp} />
        </BindLogic>
    )
}

function buildInlineTraceQuery(traceId: string, timestamp?: string): DataTableNode {
    const parsedDate = timestamp ? dayjs(timestamp) : null

    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.TraceQuery,
            traceId,
            dateRange: parsedDate
                ? {
                      date_from: parsedDate.subtract(EXCEPTION_LOOKUP_WINDOW_MINUTES, 'minutes').toISOString(),
                      date_to: parsedDate.add(EXCEPTION_LOOKUP_WINDOW_MINUTES, 'minutes').toISOString(),
                  }
                : {
                      date_from: '-30d',
                  },
        },
    }
}

function AITraceTabInner({
    traceId,
    spanId,
    timestamp,
}: {
    traceId: string
    spanId?: string | null
    timestamp?: string
}): JSX.Element {
    const { trace, event, responseLoading, responseError } = useValues(aiObservabilityTraceDataLogic)
    const selectedItem = event ?? trace ?? null
    const traceUrl = urls.aiObservabilityTrace(traceId, {
        ...(spanId ? { span_id: spanId } : {}),
        ...(timestamp ? { exception_ts: timestamp } : {}),
    })

    if (responseLoading) {
        return <SpinnerOverlay />
    }

    if (responseError) {
        return <InsightErrorState />
    }

    if (!trace) {
        return <InsightEmptyState heading="AI trace not found" detail="No AI trace was found for this exception." />
    }

    return (
        <div className="flex flex-col flex-1 min-h-0 overflow-y-auto bg-surface-primary">
            <div className="flex items-center justify-between gap-2 px-3 py-2 border-b shrink-0">
                <div className="min-w-0">
                    <div className="font-semibold truncate">
                        {selectedItem ? formatLLMEventTitle(selectedItem) : trace.id}
                    </div>
                    <div className="text-xs text-muted truncate">
                        Trace <code>{trace.id}</code>
                        {spanId ? (
                            <>
                                {' · '}Span <code>{spanId}</code>
                            </>
                        ) : null}
                    </div>
                </div>
                <LemonButton size="xsmall" type="secondary" to={traceUrl} targetBlank>
                    Open trace
                </LemonButton>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto p-3">
                {selectedItem ? <InlineAITraceEvent trace={trace} event={selectedItem} /> : null}
            </div>
        </div>
    )
}

function InlineAITraceEvent({ trace, event }: { trace: LLMTrace; event: LLMTrace | LLMTraceEvent }): JSX.Element {
    if (!isLLMEvent(event)) {
        return (
            <LLMInputOutput
                inputDisplay={<JSONValueDisplay value={event.inputState} />}
                outputDisplay={event.outputState ? <JSONValueDisplay value={event.outputState} /> : null}
                bordered
            />
        )
    }

    if (event.event === '$ai_generation') {
        return (
            <EventContentGeneration
                eventId={event.id}
                traceId={trace.id}
                rawInput={event.properties.$ai_input}
                rawOutput={event.properties.$ai_output_choices ?? event.properties.$ai_output}
                tools={event.properties.$ai_tools}
                errorData={event.properties.$ai_error}
                httpStatus={event.properties.$ai_http_status}
                raisedError={event.properties.$ai_is_error === true}
            />
        )
    }

    if (event.event === '$ai_embedding') {
        return (
            <EventContentDisplayAsync
                eventId={event.id}
                rawInput={event.properties.$ai_input}
                rawOutput="Embedding vector generated"
            />
        )
    }

    if (event.event === '$ai_span') {
        return (
            <EventContentDisplayAsync
                eventId={event.id}
                rawInput={event.properties.$ai_input_state}
                rawOutput={event.properties.$ai_output_state ?? event.properties.$ai_error}
                raisedError={event.properties.$ai_is_error === true}
            />
        )
    }

    return <JSONViewer src={event} collapsed={2} />
}
