import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { replayScannerLogic } from '../replayScannerLogic'

interface Props {
    scannerId: string
    tabId: string
}

export function ScannerQuotaForecast({ scannerId, tabId }: Props): JSX.Element | null {
    const { scanner, scannerEstimate, scannerEstimateLoading } = useValues(replayScannerLogic({ id: scannerId, tabId }))

    if (!scanner) {
        return null
    }

    const samplingRatio = Math.max(0, Math.min(scanner.sampling_rate, 1))
    const samplingPercent = Math.round(samplingRatio * 1000) / 10
    const samplingLabel = samplingPercent.toFixed(samplingPercent < 1 ? 2 : 1)

    return (
        <div className="border rounded p-3 bg-bg-light space-y-2">
            <div className="flex items-center justify-between">
                <span className="text-sm font-medium">Estimated impact</span>
                <span className="text-sm tabular-nums text-muted">{samplingLabel}% sampling</span>
            </div>
            <LemonProgress percent={Math.round(samplingRatio * 100)} />
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
                    About <strong>{scannerEstimate.estimated_observations_per_month.toLocaleString()}</strong>{' '}
                    observations a month at this sampling. Based on{' '}
                    <strong>{scannerEstimate.matched_sessions_in_window.toLocaleString()}</strong> matching recordings
                    in the last {scannerEstimate.window_days} days.
                </div>
            ) : (
                <div className="text-xs text-muted">Estimate unavailable — try adjusting your filters.</div>
            )}
        </div>
    )
}
