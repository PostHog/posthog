import { LemonTag, Tooltip } from '@posthog/lemon-ui'
import classNames from 'classnames'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { lowercaseFirstLetter } from 'lib/utils'
import React from 'react'

import { EventType } from '~/types'

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
                <MetadataTag label="Model" copyable>
                    {model}
                </MetadataTag>
            )}
            {typeof totalCostUsd === 'number' && (
                <MetadataTag label="Total generation cost">{`$${Math.round(totalCostUsd * 10e6) / 10e6}`}</MetadataTag>
            )}
        </div>
    )
}

function MetadataTag({
    children,
    label,
    copyable = false,
}: {
    children: string
    label: string
    copyable?: boolean
}): JSX.Element {
    let wrappedChildren: React.ReactNode = children
    if (copyable) {
        wrappedChildren = (
            <CopyToClipboardInline iconSize="xsmall" description={lowercaseFirstLetter(label)} tooltipMessage={label}>
                {children}
            </CopyToClipboardInline>
        )
    } else {
        wrappedChildren = <Tooltip title={label}>{children}</Tooltip>
    }

    return <LemonTag className="bg-bg-light cursor-default">{wrappedChildren}</LemonTag>
}
