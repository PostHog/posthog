import { useValues } from 'kea'

import { LemonCard, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'

import { replayScannerLogic } from '../replayScannerLogic'
import { ScannerCreditLimit } from './ScannerCreditLimit'
import { ScannerQuotaForecast } from './ScannerQuotaForecast'

/** How much of the matching traffic to spend on: what the scanner watches is set on the previous step. */
export function ScannerBudget({ scannerId }: { scannerId: string }): JSX.Element {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))

    if (!scanner) {
        return <div className="text-muted">Loading…</div>
    }

    return (
        <div className="space-y-6">
            <LemonField name="sampling_rate">
                {({ value, onChange }) => {
                    const ratio = typeof value === 'number' ? value : 0
                    const samplingPercent = Math.round(ratio * 1000) / 10
                    return (
                        <LemonCard hoverEffect={false} className="p-3 space-y-3">
                            <div className="space-y-1">
                                <LemonLabel>Sampling</LemonLabel>
                                <div className="text-xs text-muted">
                                    Each observation counts against your monthly Vision quota.
                                </div>
                            </div>
                            <div className="flex items-center gap-4">
                                <div className="flex-1">
                                    <LemonSlider
                                        value={samplingPercent}
                                        onChange={(v) => onChange(v / 100)}
                                        min={0.1}
                                        max={100}
                                        step={0.1}
                                    />
                                </div>
                                <div className="w-24">
                                    <LemonInput
                                        type="number"
                                        value={samplingPercent}
                                        onChange={(v) => onChange(Math.min(100, Number(v) || 0) / 100)}
                                        min={0.1}
                                        max={100}
                                        step={0.1}
                                        suffix={<span>%</span>}
                                        status={samplingPercent < 0.1 ? 'danger' : undefined}
                                    />
                                </div>
                            </div>
                        </LemonCard>
                    )
                }}
            </LemonField>

            <ScannerCreditLimit scannerId={scannerId} />

            <ScannerQuotaForecast scannerId={scannerId} />
        </div>
    )
}
