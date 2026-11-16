import { IconTrending } from '@posthog/icons'
import { LemonCard, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'

import type { KpiCardContent, KpiDelta } from './promptReport'

const DeltaTag = ({ delta }: { delta: KpiDelta }): JSX.Element => {
    const Icon =
        delta.direction === 'flat' ? IconTrendingFlat : delta.direction === 'up' ? IconTrending : IconTrendingDown
    return (
        <Tooltip title={delta.tooltip}>
            <LemonTag
                type={delta.direction === 'flat' ? 'muted' : delta.direction === 'up' ? 'success' : 'danger'}
                size="small"
                icon={<Icon />}
                className="tabular-nums"
            >
                {delta.label}
            </LemonTag>
        </Tooltip>
    )
}

export const ContentAutopilotPromptKpiCard = ({
    label,
    description,
    value,
    note,
    delta,
    'data-attr': dataAttr,
}: KpiCardContent & {
    label: string
    description: string
    'data-attr'?: string
}): JSX.Element => (
    <LemonCard hoverEffect={false} className="p-3 flex flex-col gap-1 min-w-0" data-attr={dataAttr}>
        <div className="flex items-center justify-between gap-2">
            <Tooltip title={description}>
                <span className="text-muted text-xs font-semibold uppercase truncate">{label}</span>
            </Tooltip>
            {delta ? <DeltaTag delta={delta} /> : null}
        </div>
        <span className="text-2xl font-semibold tabular-nums">{value}</span>
        <span className="text-muted text-xs">{note}</span>
    </LemonCard>
)
