import clsx from 'clsx'

import { LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { lowercaseFirstLetter } from 'lib/utils'

import { CostBreakdownTooltip } from '../components/CostBreakdownTooltip'
import { MetadataTag } from '../components/MetadataTag'
import { CostContext, formatLLMCost, hasCostBreakdown } from '../utils'

export function MetadataHeader({
    inputTokens,
    outputTokens,
    costContext,
    model,
    latency,
    className,
    isError,
    cacheReadTokens,
    cacheWriteTokens,
    timestamp,
    timeToFirstToken,
    isStreaming,
}: {
    inputTokens?: number
    outputTokens?: number
    cacheReadTokens?: number
    cacheWriteTokens?: number
    costContext?: CostContext
    model?: string
    latency?: number
    isError?: boolean
    className?: string
    timestamp?: string
    timeToFirstToken?: number
    isStreaming?: boolean
}): JSX.Element {
    return (
        <div className={clsx('flex flex-wrap gap-2', className)}>
            {isError && <LemonTag type="danger">Error</LemonTag>}
            {typeof latency === 'number' && (
                <MetadataTag label="Latency">{`${Math.round(latency * 10e2) / 10e2}s latency`}</MetadataTag>
            )}
            {typeof timeToFirstToken === 'number' && isStreaming && (
                <MetadataTag label="Time to first token">
                    {timeToFirstToken < 1
                        ? `${Math.round(timeToFirstToken * 1000)} ms`
                        : `${timeToFirstToken.toFixed(2)}s TTFT`}
                </MetadataTag>
            )}
            {timestamp && <MetadataTag label="Timestamp">{dayjs(timestamp).format('MMM D, YYYY h:mm A')}</MetadataTag>}
            {typeof inputTokens === 'number' && typeof outputTokens === 'number' && (
                <MetadataTag label="Token usage">
                    {`${inputTokens} prompt tokens → ${outputTokens} completion tokens (∑ ${
                        inputTokens + outputTokens
                    })`}
                </MetadataTag>
            )}
            {typeof cacheReadTokens === 'number' && cacheReadTokens > 0 && (
                <MetadataTag label="Cache read">{`${cacheReadTokens} cache read tokens`}</MetadataTag>
            )}
            {typeof cacheWriteTokens === 'number' && cacheWriteTokens > 0 && (
                <MetadataTag label="Cache write">{`${cacheWriteTokens} cache write tokens`}</MetadataTag>
            )}
            {model && (
                <MetadataTag label="Model" textToCopy={lowercaseFirstLetter(model)}>
                    {model}
                </MetadataTag>
            )}
            {costContext && (
                <MetadataTag
                    label="Total generation cost"
                    tooltipContent={
                        hasCostBreakdown(costContext) ? <CostBreakdownTooltip costContext={costContext} /> : undefined
                    }
                >
                    {formatLLMCost(costContext.totalCost)}
                </MetadataTag>
            )}
        </div>
    )
}
