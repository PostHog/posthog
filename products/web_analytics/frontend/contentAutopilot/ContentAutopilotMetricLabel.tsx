import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

export const ContentAutopilotMetricLabel = ({
    label,
    description,
    'data-attr': dataAttr,
}: {
    label: string
    description: string
    'data-attr'?: string
}): JSX.Element => (
    <span className="inline-flex items-center gap-1" data-attr={dataAttr}>
        {label}
        <Tooltip title={description}>
            <IconInfo className="text-muted size-3.5" />
        </Tooltip>
    </span>
)
