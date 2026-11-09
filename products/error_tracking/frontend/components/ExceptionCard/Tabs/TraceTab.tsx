import { useValues } from 'kea'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { usableId } from 'lib/components/ViewTraceButton/usableId'
import { TabsContent } from 'lib/ui/quill'

import { TraceEmbed } from 'products/tracing/frontend/components/TraceEmbed/TraceEmbed'

import { exceptionCardLogic } from '../exceptionCardLogic'
import { TabSpinner } from './TabSpinner'

export interface TraceTabProps {
    eventId?: string
    timestamp?: string
}

export function TraceTab({ eventId, timestamp }: TraceTabProps): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)
    const { spanId, traceId } = useValues(errorPropertiesLogic)
    const usableTraceId = usableId(traceId)

    return (
        <TabsContent value="trace" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            {loading ? (
                <TabSpinner />
            ) : !usableTraceId ? (
                <EmptyMessage
                    title="No trace found"
                    description="There is no trace ID on this exception. An exception links to its trace when it is captured inside a traced request."
                    size="small"
                />
            ) : (
                <TraceEmbed
                    viewId={`exception-${eventId ?? usableTraceId}`}
                    trace={{ traceId: usableTraceId, spanId: usableId(spanId), ts: timestamp }}
                    surface="exception_card"
                    data-attr="error-tracking-trace-tab"
                />
            )}
        </TabsContent>
    )
}
