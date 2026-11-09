import { useValues } from 'kea'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { TabsContent } from 'lib/ui/quill'

import { TraceEmbed } from 'products/tracing/frontend/components/TraceEmbed/TraceEmbed'

import { exceptionCardLogic } from '../exceptionCardLogic'
import { TabSpinner } from './TabSpinner'

export interface TraceTabProps {
    eventId?: string
    traceId: string | null
    spanId: string | null
    timestamp?: string
}

export function TraceTab({ eventId, traceId, spanId, timestamp }: TraceTabProps): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)

    return (
        <TabsContent value="trace" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            {loading ? (
                <TabSpinner />
            ) : !traceId ? (
                <EmptyMessage
                    title="No trace found"
                    description="There is no trace ID on this exception. An exception links to its trace when it is captured inside a traced request."
                    size="small"
                />
            ) : (
                <TraceEmbed
                    viewId={`exception-${eventId ?? traceId}`}
                    trace={{ traceId, spanId, ts: timestamp }}
                    surface="exception_card"
                    data-attr="error-tracking-trace-tab"
                />
            )}
        </TabsContent>
    )
}
