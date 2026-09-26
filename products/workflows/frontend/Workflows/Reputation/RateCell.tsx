import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import {
    RATE_THRESHOLDS,
    RateKind,
    RateLevel,
    classifyRate,
    formatRate,
    RATE_KINDS,
    minimumVolumeToClassify,
} from './reputationUtils'

const RATE_LEVEL_TAG: Record<RateLevel, { label: string; type: LemonTagType }> = {
    healthy: { label: 'Healthy', type: 'success' },
    elevated: { label: 'Elevated', type: 'warning' },
    high: { label: 'High', type: 'danger' },
}

export function RateCell({
    rate,
    kind,
    // What the rate divides by, which differs per kind: sends for bounces, and for complaints the
    // far smaller set of deliveries the provider reports them for.
    volume,
}: {
    rate: number
    kind: RateKind
    volume: number
}): JSX.Element {
    const label = `${RATE_KINDS[kind].event} rate`
    const minimumVolume = minimumVolumeToClassify(kind)
    if (volume < minimumVolume) {
        const noun = kind === 'bounce' ? 'emails sent' : 'deliveries this provider reports complaints for'
        return (
            <Tooltip
                title={`Too little volume to judge the ${label}. Under ${humanFriendlyNumber(minimumVolume)} ${noun}, one ${RATE_KINDS[kind].event} on its own would put this above ${formatRate(RATE_THRESHOLDS[kind].elevated)}.`}
            >
                <span className="tabular-nums text-secondary cursor-default">{formatRate(rate)}</span>
            </Tooltip>
        )
    }
    const level = classifyRate(rate, kind)
    const tag = RATE_LEVEL_TAG[level]
    const highPct = formatRate(RATE_THRESHOLDS[kind].high)
    const elevatedPct = formatRate(RATE_THRESHOLDS[kind].elevated)
    const tooltip =
        level === 'high'
            ? `Above ${highPct} ${label}. This damages deliverability and, if it keeps climbing, sending for this project can be paused.`
            : level === 'elevated'
              ? `Above ${elevatedPct} ${label}. Worth investigating before it reaches ${highPct}.`
              : `Below ${elevatedPct} ${label}.`
    return (
        <Tooltip title={tooltip}>
            <span className="inline-flex items-center gap-2 cursor-default justify-end">
                <LemonTag type={tag.type} size="small">
                    {tag.label}
                </LemonTag>
                <span className="tabular-nums">{formatRate(rate)}</span>
            </span>
        </Tooltip>
    )
}
