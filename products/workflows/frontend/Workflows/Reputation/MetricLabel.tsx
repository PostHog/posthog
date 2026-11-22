import { Tooltip } from '@posthog/lemon-ui'

export function MetricLabel({
    label,
    tooltip,
    description,
}: {
    label: string
    tooltip: string
    description?: string
}): JSX.Element {
    const labelNode = (
        <Tooltip title={tooltip}>
            <div className="text-secondary text-xs border-b border-dotted border-current inline-block cursor-default">
                {label}
            </div>
        </Tooltip>
    )
    if (!description) {
        return labelNode
    }
    return (
        <div>
            {labelNode}
            <div className="text-secondary text-xs mt-1">{description}</div>
        </div>
    )
}
