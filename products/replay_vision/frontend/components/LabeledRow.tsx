import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

/** A label-above-content row used across the readonly config and observation detail cards. */
export function LabeledRow({
    label,
    tooltip,
    aside,
    children,
}: {
    label: string
    tooltip?: string
    /** Sits on the label's line, for a qualifier of the value such as the model's confidence. */
    aside?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <div>
            <div className="flex items-center gap-1 text-xs text-muted mb-0.5">
                {label}
                {tooltip && (
                    <Tooltip title={tooltip}>
                        <IconInfo className="text-sm" />
                    </Tooltip>
                )}
                {aside && <span className="ml-1">{aside}</span>}
            </div>
            <div className="text-sm min-w-0">{children}</div>
        </div>
    )
}
