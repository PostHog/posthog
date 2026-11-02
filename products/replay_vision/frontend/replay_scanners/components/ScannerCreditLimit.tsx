import { useActions, useValues } from 'kea'

import { LemonCard, LemonInput, LemonSegmentedButton, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { creditsToUsd, formatCredits } from '../../utils/credits'
import {
    CreditLimitUnit,
    creditsToObservations,
    observationsToCredits,
    replayScannerLogic,
} from '../replayScannerLogic'
import { MAX_CREDIT_LIMIT } from '../types'

interface ScannerCreditLimitProps {
    scannerId: string
}

export function ScannerCreditLimit({ scannerId }: ScannerCreditLimitProps): JSX.Element {
    const { creditLimitState, scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const { setScannerValues, setCreditLimitUnit } = useActions(replayScannerLogic({ id: scannerId }))
    const {
        limit,
        unit,
        observationLimit,
        isOn,
        estimatedMonthly,
        estimatedMonthlyObservations,
        creditsPerObservation,
        isBelowEstimate,
        cannotAffordOneScan,
        seedValue,
    } = creditLimitState
    const observationPrice = unit === 'observations' ? creditsPerObservation : null
    const input =
        observationPrice != null
            ? {
                  value: observationLimit,
                  max: creditsToObservations(MAX_CREDIT_LIMIT, observationPrice),
                  suffix: 'observations',
                  toCredits: (amount: number) => observationsToCredits(amount, observationPrice),
                  summary: limit != null ? `${formatCredits(limit)} per period` : null,
              }
            : {
                  value: limit,
                  max: MAX_CREDIT_LIMIT,
                  suffix: 'credits',
                  toCredits: (amount: number) => amount,
                  summary: limit != null ? `≈ ${creditsToUsd(limit)} per period` : null,
              }

    return (
        <LemonField name="credit_limit">
            {() => (
                <LemonCard hoverEffect={false} className="p-3 space-y-3">
                    <div className="flex items-start justify-between gap-2">
                        <div className="space-y-1">
                            <LemonLabel htmlFor="vision-scanner-free-only">Free credits only</LemonLabel>
                            <div className="text-xs text-muted">
                                Scan only while your organization has free monthly credits left, so this scanner never
                                adds to your bill. It pauses when they run out and starts again when the billing period
                                resets.
                            </div>
                        </div>
                        <LemonSwitch
                            checked={!!scanner?.free_only}
                            onChange={(checked) => setScannerValues({ free_only: checked })}
                            id="vision-scanner-free-only"
                            data-attr="vision-scanner-free-only-toggle"
                        />
                    </div>
                    <div className="flex items-start justify-between gap-2">
                        <div className="space-y-1">
                            <LemonLabel htmlFor="vision-scanner-credit-limit">Scanner limit</LemonLabel>
                            <div className="text-xs text-muted">
                                Cap what this scanner spends in a billing period. Your organization's limit still
                                applies.
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
                            id="vision-scanner-credit-limit"
                            data-attr="vision-scanner-credit-limit-toggle"
                        />
                    </div>
                    {isOn && (
                        <>
                            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                                <LemonSegmentedButton<CreditLimitUnit>
                                    size="small"
                                    value={unit}
                                    onChange={setCreditLimitUnit}
                                    options={[
                                        {
                                            value: 'credits',
                                            label: 'Credits',
                                            'data-attr': 'vision-scanner-credit-limit-unit-credits',
                                        },
                                        {
                                            value: 'observations',
                                            label: 'Observations',
                                            'data-attr': 'vision-scanner-credit-limit-unit-observations',
                                            disabledReason:
                                                creditsPerObservation == null
                                                    ? 'The price of one observation for this model is not known yet'
                                                    : undefined,
                                        },
                                    ]}
                                />
                                <div className="w-48">
                                    <LemonInput
                                        type="number"
                                        value={input.value ?? undefined}
                                        onChange={(v) =>
                                            // The toggle is materialized on edit too, so clearing a loaded limit blocks the save.
                                            setScannerValues({
                                                credit_limit_enabled: true,
                                                credit_limit:
                                                    v == null || !Number.isFinite(v)
                                                        ? null
                                                        : input.toCredits(Math.max(1, Math.round(v))),
                                            })
                                        }
                                        min={1}
                                        max={input.max}
                                        step={1}
                                        suffix={<span>{input.suffix}</span>}
                                    />
                                </div>
                                <span className="text-sm text-muted">
                                    {input.summary}
                                    {input.summary != null && estimatedMonthly != null && ' · '}
                                    {estimatedMonthly != null &&
                                        `Estimated usage: ${creditsToUsd(estimatedMonthly)} a month`}
                                </span>
                            </div>
                            {cannotAffordOneScan ? (
                                <div className="text-xs text-warning">
                                    {observationPrice != null
                                        ? 'This limit allows 0 observations, so the scanner stops before it scans anything. Raise it to at least 1 observation.'
                                        : `One scan by this scanner costs ${creditsPerObservation} credits, so this limit stops it before it scans anything. Raise it to at least ${creditsPerObservation} credits.`}
                                </div>
                            ) : (
                                isBelowEstimate && (
                                    <div className="text-xs text-warning">
                                        This is below the estimated{' '}
                                        {observationPrice != null && estimatedMonthlyObservations != null
                                            ? `${estimatedMonthlyObservations.toLocaleString('en-US')} observations`
                                            : creditsToUsd(estimatedMonthly ?? 0)}{' '}
                                        a month, so the scanner is likely to stop before the period resets.
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
