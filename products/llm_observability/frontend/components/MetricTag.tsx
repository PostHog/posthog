import { LemonTag } from '@posthog/lemon-ui'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { identifierToHuman } from 'lib/utils'

interface MetricTagProps {
    properties: Record<string, any>
}

export function MetricTag({ properties }: MetricTagProps): JSX.Element {
    const { $ai_score_name: metricName, $ai_score_value: metricValue } = properties

    const strValue = String(metricValue)
    const isValueLong = strValue.length > 10

    const name = metricName ? identifierToHuman(metricName) : 'Metric'
    const value = isValueLong ? `${strValue.slice(0, 10)}...` : strValue
    const title = `${name}: ${value}`

    const description = (
        <>
            {metricName && (
                <>
                    Metric: {metricName}
                    <br />
                    <br />
                </>
            )}
            {metricValue}
        </>
    )

    return (
        <LemonTag className="bg-bg-light cursor-default">
            <CopyToClipboardInline
                iconSize="xsmall"
                description={strValue}
                tooltipMessage={isValueLong ? description : null}
            >
                {title}
            </CopyToClipboardInline>
        </LemonTag>
    )
}
