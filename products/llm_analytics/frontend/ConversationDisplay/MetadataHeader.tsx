import classNames from 'classnames'

import { LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { lowercaseFirstLetter } from 'lib/utils'

import { MetadataTag } from '../components/MetadataTag'

export function MetadataHeader({
    inputTokens,
    outputTokens,
    totalCostUsd,
    model,
    latency,
    className,
    isError,
    cacheReadTokens,
    cacheWriteTokens,
    timestamp,
}: {
    inputTokens?: number
    outputTokens?: number
    cacheReadTokens?: number
    cacheWriteTokens?: number
    totalCostUsd?: number
    model?: string
    latency?: number
    isError?: boolean
    className?: string
    timestamp?: string
}): JSX.Element {
    return (
        <div className={classNames('flex flex-wrap gap-2', className)}>
            {isError && <LemonTag type="danger">Error</LemonTag>}
            {typeof latency === 'number' && (
                <MetadataTag label="Latency">{`${Math.round(latency * 10e2) / 10e2} s of latency`}</MetadataTag>
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
            {typeof totalCostUsd === 'number' && (
                <MetadataTag label="Total generation cost">{`$${Math.round(totalCostUsd * 10e6) / 10e6}`}</MetadataTag>
            )}
        </div>
    )
}
