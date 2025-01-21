import classNames from 'classnames'
import { lowercaseFirstLetter } from 'lib/utils'

import { EventType } from '~/types'

import { MetadataTag } from '../components/MetadataTag'

export function MetadataHeader({
    eventProperties,
    className,
}: {
    eventProperties: EventType['properties']
    className?: string
}): JSX.Element {
    const {
        $ai_input_tokens: inputTokens,
        $ai_output_tokens: outputTokens,
        $ai_total_cost_usd: totalCostUsd,
        $ai_model: model,
        $ai_latency: latency,
    } = eventProperties

    return (
        <div className={classNames('flex flex-wrap gap-2', className)}>
            {typeof latency === 'number' && (
                <MetadataTag label="Latency">{`${Math.round(latency * 10e2) / 10e2} s of latency`}</MetadataTag>
            )}
            {typeof inputTokens === 'number' && typeof outputTokens === 'number' && (
                <MetadataTag label="Token usage">
                    {`${inputTokens} prompt tokens → ${outputTokens} completion tokens (∑ ${
                        inputTokens + outputTokens
                    })`}
                </MetadataTag>
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
