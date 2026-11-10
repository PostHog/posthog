import { IconInfo } from '@posthog/icons'
import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

/** A label-above-content row for observation detail panes. */
export function QuillLabeledRow({
    label,
    tooltip,
    aside,
    children,
}: {
    label: string
    tooltip?: string
    aside?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <div>
            <div className="flex items-center gap-1 text-xs text-muted-foreground mb-0.5">
                {label}
                {tooltip && (
                    <Tooltip>
                        <TooltipTrigger render={<span className="flex" />}>
                            <IconInfo className="text-sm" />
                        </TooltipTrigger>
                        <TooltipContent>{tooltip}</TooltipContent>
                    </Tooltip>
                )}
                {aside && <span className="ml-1">{aside}</span>}
            </div>
            <div className="text-sm min-w-0">{children}</div>
        </div>
    )
}
