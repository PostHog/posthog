import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'

export function VisionQuotaMeter(): JSX.Element | null {
    const { quota, quotaLoading } = useValues(visionQuotaLogic)

    if (!quota) {
        if (quotaLoading) {
            return (
                <div className="border rounded p-3 bg-bg-light space-y-2">
                    <div className="flex items-center justify-between">
                        <LemonSkeleton className="h-4 w-48" />
                        <LemonSkeleton className="h-4 w-20" />
                    </div>
                    <LemonSkeleton className="h-2 w-full" />
                    <LemonSkeleton className="h-3 w-24" />
                </div>
            )
        }
        return null
    }

    const ratio = quota.monthly_quota > 0 ? Math.min(quota.usage_this_month / quota.monthly_quota, 1) : 0
    const percent = Math.round(ratio * 100)
    const strokeColor = quota.exhausted ? 'var(--danger)' : ratio >= 0.8 ? 'var(--warning)' : 'var(--success)'

    return (
        <div className="border rounded p-3 bg-bg-light space-y-2">
            <div className="flex items-center justify-between">
                <Tooltip title="Observations are paused once this quota is reached, until next month.">
                    <span className="text-sm font-medium">Vision observations this month</span>
                </Tooltip>
                <span className="text-sm tabular-nums">
                    {quota.usage_this_month.toLocaleString()} / {quota.monthly_quota.toLocaleString()}
                </span>
            </div>
            <LemonProgress percent={percent} strokeColor={strokeColor} />
            <div className="text-xs text-muted">
                {quota.exhausted ? (
                    <span className="text-danger">Quota reached.</span>
                ) : (
                    <>{quota.remaining.toLocaleString()} remaining</>
                )}
            </div>
        </div>
    )
}
