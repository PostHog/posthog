import { useActions, useValues } from 'kea'

import { LemonCard, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { creditsToUsd } from '../../utils/credits'
import { replayScannerLogic } from '../replayScannerLogic'
import { MAX_CREDIT_LIMIT } from '../types'

interface ScannerCreditLimitProps {
    scannerId: string
}

export function ScannerCreditLimit({ scannerId }: ScannerCreditLimitProps): JSX.Element {
    const { creditLimitState } = useValues(replayScannerLogic({ id: scannerId }))
    const { setScannerValues } = useActions(replayScannerLogic({ id: scannerId }))
    const { limit, isOn, estimatedMonthly, creditsPerObservation, isBelowEstimate, cannotAffordOneScan, seedValue } =
        creditLimitState

    return (
        <LemonField name="credit_limit">
            {() => (
                <LemonCard hoverEffect={false} className="p-3 space-y-3">
                    <div className="flex items-start justify-between gap-2">
                        <div className="space-y-1">
                            <LemonLabel>Credit limit</LemonLabel>
                            <div className="text-xs text-muted">
                                Cap what this scanner spends in a billing period, on top of your organization's limit.
                            </div>
                        </div>
                        <LemonSwitch
                            checked={isOn}
                            onChange={(checked) =>
                                setScannerValues({
                                    credit_limit_enabled: checked,
                                    credit_limit: checked ? seedValue : null,
                                })
                            }
                            data-attr="vision-scanner-credit-limit-toggle"
                        />
                    </div>
                    {isOn && (
                        <>
                            <div className="flex items-center gap-4">
                                <div className="w-40">
                                    <LemonInput
                                        type="number"
                                        value={limit ?? undefined}
                                        onChange={(v) =>
                                            // The toggle is materialized on edit too, so clearing a loaded limit blocks the save.
                                            setScannerValues({
                                                credit_limit_enabled: true,
                                                credit_limit:
                                                    v == null || !Number.isFinite(v)
                                                        ? null
                                                        : Math.max(1, Math.round(v)),
                                            })
                                        }
                                        min={1}
                                        max={MAX_CREDIT_LIMIT}
                                        step={1}
                                        suffix={<span>credits</span>}
                                    />
                                </div>
                                <span className="text-sm text-muted">
                                    {limit != null && `≈ ${creditsToUsd(limit)} per period`}
                                    {limit != null && estimatedMonthly != null && ' · '}
                                    {estimatedMonthly != null &&
                                        `Estimated usage: ${creditsToUsd(estimatedMonthly)} a month`}
                                </span>
                            </div>
                            {cannotAffordOneScan ? (
                                <div className="text-xs text-warning">
                                    One scan by this scanner costs {creditsPerObservation} credits, so this limit stops
                                    it before it scans anything. Raise it to at least {creditsPerObservation} credits.
                                </div>
                            ) : (
                                isBelowEstimate && (
                                    <div className="text-xs text-warning">
                                        This is below the estimated {creditsToUsd(estimatedMonthly ?? 0)} a month, so
                                        the scanner is likely to stop before the period resets.
                                    </div>
                                )
                            )}
                            <div className="text-xs text-muted">
                                When this scanner reaches its limit, it stops scanning until the next billing period. It
                                stays enabled, but sessions it skipped this billing period aren't scanned later, even
                                after you raise the limit.
                            </div>
                        </>
                    )}
                </LemonCard>
            )}
        </LemonField>
    )
}
