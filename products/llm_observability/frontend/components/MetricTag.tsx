import { LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { identifierToHuman } from 'lib/utils'

interface MetricTagProps {
    properties: Record<string, any>
}

export function MetricTag({ properties }: MetricTagProps): JSX.Element {
    const { $ai_metric_name: metricName, $ai_metric_value: metricValue } = properties
    const strValue = String(metricValue)
    const isValueLong = strValue.length > 10

    const name = metricName ? identifierToHuman(metricName) : 'Metric'
    const value = isValueLong ? `${strValue.slice(0, 10)}...` : strValue
    const title = `${name}: ${value}`

    const description = (
        <>
            {metricName && (
                <span>
                    Metric: {metricName}
                    <br />
                    <br />
                </span>
            )}
            {metricValue}
            <br />
            <span>Click to copy the value</span>
        </>
    )

    return (
        <LemonTag className="bg-surface-primary cursor-default">
            <CopyToClipboardInline
                iconSize="xsmall"
                description="metric"
                explicitValue={strValue}
                tooltipMessage={isValueLong ? description : 'Click to copy the value'}
            >
                {title}
            </CopyToClipboardInline>
        </LemonTag>
    )
}
