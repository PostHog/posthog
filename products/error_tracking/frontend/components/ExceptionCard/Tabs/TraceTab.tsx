import { useValues } from 'kea'
import { Suspense } from 'react'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { TabsContent } from 'lib/ui/quill'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { exceptionCardLogic } from '../exceptionCardLogic'
import { TabSpinner } from './TabSpinner'

// The trace view is large, and most cards never open this tab.
const TraceEmbed = lazyWithRetry(() =>
    import('products/tracing/frontend/components/TraceEmbed/TraceEmbed').then((m) => ({ default: m.TraceEmbed }))
)

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
                <Suspense fallback={<TabSpinner />}>
                    <TraceEmbed
                        viewId={`exception-${eventId ?? traceId}`}
                        trace={{ traceId, spanId, ts: timestamp }}
                        surface="exception_card"
                        data-attr="error-tracking-trace-tab"
                    />
                </Suspense>
            )}
        </TabsContent>
    )
}
