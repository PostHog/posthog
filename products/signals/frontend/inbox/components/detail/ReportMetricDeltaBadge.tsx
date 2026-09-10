import clsx from 'clsx'

import {
    type IconComponent,
    IconArrowRightDown,
    IconArrowUpRight,
    IconMinusSmall,
    type IconProps,
} from '@posthog/icons'

import type { ReportMetricDelta, ReportMetricDeltaDirection, ReportMetricDeltaTone } from '../../utils/reportMetrics'

const DELTA_ICON: Record<ReportMetricDeltaDirection, IconComponent<IconProps>> = {
    up: IconArrowUpRight,
    down: IconArrowRightDown,
    flat: IconMinusSmall,
}

// Color carries harm, not the arithmetic sign, so the figure itself stays neutral and only this
// badge is red or green.
const DELTA_TONE_CLASS: Record<ReportMetricDeltaTone, string> = {
    good: 'text-success',
    bad: 'text-danger',
    neutral: 'text-tertiary',
}

/** The change of a metric value against the one it is compared with, such as `+50%` or `3.3×`. */
export function ReportMetricDeltaBadge({ delta }: { delta: ReportMetricDelta }): JSX.Element {
    const Icon = DELTA_ICON[delta.direction]

    return (
        <span
            className={clsx('inline-flex items-center gap-0.5 font-medium', DELTA_TONE_CLASS[delta.tone])}
            data-attr="report-metric-delta"
            data-tone={delta.tone}
        >
            <Icon className="size-3" aria-hidden />
            {delta.label}
        </span>
    )
}
