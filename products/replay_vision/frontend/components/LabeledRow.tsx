import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

/** A label-above-content row used across the readonly config and observation detail cards. */
export function LabeledRow({
    label,
    tooltip,
    children,
}: {
    label: string
    tooltip?: string
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
            </div>
            <div className="text-sm min-w-0">{children}</div>
        </div>
    )
}
