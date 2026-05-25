import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { replayScannersLogic } from '../replayScannersLogic'

const RANGE_OPTIONS: { value: 7 | 30 | 90; label: string }[] = [
    { value: 7, label: '7 days' },
    { value: 30, label: '30 days' },
    { value: 90, label: '90 days' },
]

export function VisionQuotaMeter(): JSX.Element | null {
    const { quota, usageRangeDays } = useValues(replayScannersLogic)
    const { setUsageRangeDays } = useActions(replayScannersLogic)

    if (!quota) {
        return null
    }

    const ratio = quota.limit > 0 ? Math.min(quota.used / quota.limit, 1) : 0
    const percent = Math.round(ratio * 100)
    const remaining = Math.max(quota.limit - quota.used, 0)
    const strokeColor = ratio >= 1 ? 'var(--danger)' : ratio >= 0.8 ? 'var(--warning)' : 'var(--success)'

    const policyCopy =
        quota.policy === 'block'
            ? 'Schedules pause when this quota is reached.'
            : 'Observations beyond the quota accrue against your usage-based meter.'

    const history = quota.usage_history ?? []
    const slice = history.slice(-usageRangeDays)
    const sparklineData = slice.map((p) => p.count)
    const sparklineLabels = slice.map((p) => p.date)
    const rangeTotal = slice.reduce((sum, p) => sum + p.count, 0)

    return (
        <div className="border rounded p-3 bg-bg-light space-y-3">
            <div className="space-y-1">
                <div className="flex items-center justify-between">
                    <Tooltip title={policyCopy}>
                        <span className="text-sm font-medium">Vision observations this month</span>
                    </Tooltip>
                    <span className="text-sm tabular-nums">
                        {quota.used.toLocaleString()} / {quota.limit.toLocaleString()}
                    </span>
                </div>
                <LemonProgress percent={percent} strokeColor={strokeColor} />
                <div className="text-xs text-muted">
                    {ratio >= 1 ? (
                        <span className="text-danger">Quota reached.</span>
                    ) : (
                        <>{remaining.toLocaleString()} remaining</>
                    )}
                    <span className="mx-1">·</span>
                    <span>{quota.policy === 'block' ? 'Block on overage' : 'Usage-based overage'}</span>
                </div>
            </div>
            {sparklineData.length > 0 && (
                <div>
                    <div className="flex items-center justify-between mb-1">
                        <div className="text-xs text-muted">
                            Observations per day
                            <span className="mx-1">·</span>
                            <span className="tabular-nums">{rangeTotal.toLocaleString()} in range</span>
                        </div>
                        <LemonSegmentedButton
                            size="xsmall"
                            value={usageRangeDays}
                            onChange={(value) => setUsageRangeDays(value)}
                            options={RANGE_OPTIONS}
                        />
                    </div>
                    <Sparkline data={sparklineData} labels={sparklineLabels} type="bar" className="h-12 w-full" />
                </div>
            )}
        </div>
    )
}
