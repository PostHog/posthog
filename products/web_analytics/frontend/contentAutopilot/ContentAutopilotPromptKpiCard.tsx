import { IconTrending } from '@posthog/icons'
import { LemonCard, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { percentage } from 'lib/utils/numbers'

import type { PromptRateKpi } from './promptReport'

const DeltaTag = ({ delta }: { delta: number }): JSX.Element => {
    const points = Math.round(delta * 100)
    const Icon = points === 0 ? IconTrendingFlat : points > 0 ? IconTrending : IconTrendingDown
    return (
        <Tooltip title="The latest day against the 30-day average, in percentage points">
            <LemonTag
                type={points === 0 ? 'muted' : points > 0 ? 'success' : 'danger'}
                size="small"
                icon={<Icon />}
                className="tabular-nums"
            >
                {points === 0 ? 'No change' : `${points > 0 ? '+' : ''}${points} pts`}
            </LemonTag>
        </Tooltip>
    )
}

export const ContentAutopilotPromptKpiCard = ({
    label,
    description,
    kpi,
    'data-attr': dataAttr,
}: {
    label: string
    description: string
    kpi: PromptRateKpi
    'data-attr'?: string
}): JSX.Element => (
    <LemonCard hoverEffect={false} className="p-3 flex flex-col gap-1 min-w-0" data-attr={dataAttr}>
        <div className="flex items-center justify-between gap-2">
            <Tooltip title={description}>
                <span className="text-muted text-xs font-semibold uppercase truncate">{label}</span>
            </Tooltip>
            {kpi.delta !== null ? <DeltaTag delta={kpi.delta} /> : null}
        </div>
        <span className="text-2xl font-semibold tabular-nums">
            {kpi.average === null ? 'No answers' : percentage(kpi.average, 0)}
        </span>
        <span className="text-muted text-xs">
            {kpi.latest === null || !kpi.latestDate
                ? 'Average over the last 30 days'
                : `Average over the last 30 days. On ${dayjs(kpi.latestDate).format('MMM D')}: ${percentage(kpi.latest, 0)}`}
        </span>
    </LemonCard>
)
