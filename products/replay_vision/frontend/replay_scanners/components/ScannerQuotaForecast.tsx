import { useValues } from 'kea'

import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { replayScannerLogic } from '../replayScannerLogic'

interface Props {
    scannerId: string
    tabId: string
}

const WARN_THRESHOLD = 0.8

type QuotaStatus = 'safe' | 'warning' | 'danger'

const STATUS_STYLES: Record<QuotaStatus, { bar: string; text: string }> = {
    safe: { bar: 'bg-primary', text: 'text-muted' },
    warning: { bar: 'bg-warning', text: 'text-warning' },
    danger: { bar: 'bg-danger', text: 'text-danger' },
}

export function ScannerQuotaForecast({ scannerId, tabId }: Props): JSX.Element | null {
    const { scanner, scannerEstimate, scannerEstimateLoading } = useValues(replayScannerLogic({ id: scannerId, tabId }))
    const { quota } = useValues(visionQuotaLogic)

    if (!scanner) {
        return null
    }

    const samplingRatio = Math.max(0, Math.min(scanner.sampling_rate, 1))
    const projected = scannerEstimate?.estimated_observations_per_month ?? null
    const hasCap = !!quota && quota.monthly_quota > 0
    const used = quota?.usage_this_month ?? 0
    const cap = quota?.monthly_quota ?? 0
    const total = used + (projected ?? 0)
    const totalRatio = hasCap ? total / cap : 0
    const status: QuotaStatus = !hasCap
        ? 'safe'
        : total > cap
          ? 'danger'
          : totalRatio >= WARN_THRESHOLD
            ? 'warning'
            : 'safe'
    const styles = STATUS_STYLES[status]
    const percentLabel = hasCap ? Math.round(totalRatio * 100) : 0
    const resetsOn = quota?.period_end ? dayjs(quota.period_end).format('MMM D') : null

    const usedPct = hasCap ? Math.min((used / cap) * 100, 100) : 0
    const projectedPctRaw = hasCap && projected !== null ? (projected / cap) * 100 : 0
    const projectedPct = Math.max(0, Math.min(projectedPctRaw, 100 - usedPct))
    const overflowPct = status === 'danger' ? Math.min(((total - cap) / cap) * 100, 100) : 0

    const renderBreakdown = (): JSX.Element => (
        <div className="text-xs space-y-0.5">
            <div>
                Used this month: <strong>{used.toLocaleString()}</strong>
            </div>
            <div>
                Projected from this scanner: <strong>~{(projected ?? 0).toLocaleString()}</strong>
            </div>
            <div>
                Monthly cap: <strong>{cap.toLocaleString()}</strong>
            </div>
            {resetsOn && <div className="text-muted">Resets {resetsOn}</div>}
        </div>
    )

    return (
        <div className="border rounded p-3 bg-bg-light space-y-2">
            <div className="flex items-baseline justify-between gap-3">
                <div className="text-xs font-medium uppercase tracking-wide text-muted">Estimated impact</div>
                {hasCap && projected !== null && (
                    <Tooltip title={renderBreakdown()}>
                        <span className={`text-xs tabular-nums ${styles.text}`}>
                            {percentLabel}% <span className="text-muted font-normal">of cap</span>
                        </span>
                    </Tooltip>
                )}
            </div>

            <div className="flex items-baseline justify-between gap-3">
                {projected !== null ? (
                    <div className="text-base font-semibold tabular-nums">
                        {projected.toLocaleString()}{' '}
                        <span className="text-sm font-normal text-muted">observations/month</span>
                    </div>
                ) : (
                    <div className="text-sm text-muted">—</div>
                )}
                {hasCap && (
                    <span className="text-xs text-muted tabular-nums">
                        {used.toLocaleString()} / {cap.toLocaleString()}
                    </span>
                )}
            </div>

            {hasCap && projected !== null && (
                <Tooltip title={renderBreakdown()}>
                    <div
                        className="flex h-1.5 rounded overflow-hidden bg-border-light"
                        role="meter"
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={percentLabel}
                        aria-label={`${percentLabel}% of monthly observation quota used`}
                    >
                        <div className="bg-muted" style={{ width: `${usedPct}%` }} />
                        <div className={styles.bar} style={{ width: `${projectedPct}%` }} />
                        {overflowPct > 0 && (
                            <div className="bg-danger opacity-60" style={{ width: `${overflowPct}%` }} />
                        )}
                    </div>
                </Tooltip>
            )}

            {samplingRatio === 0 ? (
                <div className="text-xs text-danger">
                    Sampling is 0%. This scanner will not produce any observations.
                </div>
            ) : scannerEstimateLoading && !scannerEstimate ? (
                <div className="text-xs text-muted flex items-center gap-2">
                    <Spinner /> Estimating from your filters…
                </div>
            ) : scannerEstimate ? (
                <div className="text-xs text-muted">
                    {status === 'danger' ? (
                        <span className="text-danger">
                            Projected to exceed your monthly cap{resetsOn ? ` (resets ${resetsOn})` : ''}. Lower the
                            sampling rate or tighten the filters.
                        </span>
                    ) : status === 'warning' ? (
                        <span className="text-warning">Projected to use a large share of your monthly cap.</span>
                    ) : (
                        <>
                            Based on <strong>{scannerEstimate.matched_sessions_in_window.toLocaleString()}</strong>{' '}
                            matching recordings in the last {scannerEstimate.window_days} days.
                        </>
                    )}
                </div>
            ) : (
                <div className="text-xs text-muted">Estimate unavailable. Try adjusting your filters.</div>
            )}
        </div>
    )
}
