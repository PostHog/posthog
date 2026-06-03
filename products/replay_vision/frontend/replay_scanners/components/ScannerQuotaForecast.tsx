import { useValues } from 'kea'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { replayScannerLogic } from '../replayScannerLogic'

interface Props {
    scannerId: string
    tabId: string
}

export function ScannerQuotaForecast({ scannerId, tabId }: Props): JSX.Element | null {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId, tabId }))

    if (!scanner) {
        return null
    }

    const samplingRatio = Math.max(0, Math.min(scanner.sampling_rate, 1))
    const samplingPercent = Math.round(samplingRatio * 1000) / 10
    const oneInN = samplingRatio > 0 ? Math.max(1, Math.round(1 / samplingRatio)) : null

    return (
        <div className="border rounded p-3 bg-bg-light space-y-2">
            <div className="flex items-center justify-between">
                <span className="text-sm font-medium">Quota impact</span>
                <span className="text-sm tabular-nums">{samplingPercent.toFixed(samplingPercent < 1 ? 2 : 1)}%</span>
            </div>
            <LemonProgress percent={Math.round(samplingRatio * 100)} />
            <div className="text-xs text-muted">
                {oneInN === null ? (
                    <span className="text-danger">Sampling is 0%. This scanner will not produce any observations.</span>
                ) : oneInN === 1 ? (
                    <>
                        Every matching recording produces one observation. Each observation counts against your monthly
                        Vision quota.
                    </>
                ) : (
                    <>
                        About <strong>1 in {oneInN.toLocaleString()}</strong> matching recordings will be observed.
                        Lower this slider to reduce monthly quota consumption; raise it for denser coverage.
                    </>
                )}
            </div>
        </div>
    )
}
