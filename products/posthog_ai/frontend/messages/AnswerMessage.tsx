import { Suspense, memo, useMemo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { splitAnswerSegments } from '../utils/answerSegments'
import { MarkdownMessage } from './MarkdownMessage'
import { MessageTemplate } from './MessageTemplate'

// The chart widget pulls in the query renderer, so its chunk loads only when an answer has a chart.
const AnswerChartWidget = lazyWithRetry(() =>
    import('../components/tool/widgets/AnswerChartWidget').then((m) => ({ default: m.AnswerChartWidget }))
)

/** An assistant answer whose chart block tags render as charts between its markdown runs. */
export const AnswerMessage = memo(function AnswerMessage({
    content,
    id,
}: {
    content: string
    id: string
}): JSX.Element {
    const segments = useMemo(() => splitAnswerSegments(content), [content])
    return (
        <div className="flex flex-col gap-2">
            {segments.map((segment, index) =>
                segment.type === 'markdown' ? (
                    <MessageTemplate key={`${id}-${index}`} type="ai" wrapperClassName="max-w-4/5">
                        <MarkdownMessage content={segment.text} id={`${id}-${index}`} />
                    </MessageTemplate>
                ) : (
                    <Suspense key={`${id}-${index}`} fallback={<LemonSkeleton className="h-96 w-full" />}>
                        <AnswerChartWidget block={segment.block} />
                    </Suspense>
                )
            )}
        </div>
    )
})
