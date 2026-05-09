import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { replayLensesLogic } from '../replayLensesLogic'

export function VisionQuotaMeter(): JSX.Element | null {
    const { quota } = useValues(replayLensesLogic)

    if (!quota) {
        return null
    }

    const ratio = quota.limit > 0 ? Math.min(quota.used / quota.limit, 1) : 0
    const percent = Math.round(ratio * 100)
    const remaining = Math.max(quota.limit - quota.used, 0)
    const bg = ratio >= 1 ? 'bg-danger' : ratio >= 0.8 ? 'bg-warning' : 'bg-success'

    const policyCopy =
        quota.policy === 'block'
            ? 'Schedules pause when this quota is reached.'
            : 'Observations beyond the quota accrue against your usage-based meter.'

    return (
        <div className="border rounded p-3 bg-bg-light flex flex-wrap items-center gap-3">
            <div className="flex-1 min-w-[200px]">
                <div className="flex items-center justify-between mb-1">
                    <Tooltip title={policyCopy}>
                        <span className="text-sm font-medium">Vision observations this month</span>
                    </Tooltip>
                    <span className="text-sm tabular-nums">
                        {quota.used.toLocaleString()} / {quota.limit.toLocaleString()}
                    </span>
                </div>
                <LemonProgress percent={percent} bgColor={bg} />
            </div>
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
    )
}
