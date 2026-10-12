import { useActions, useValues } from 'kea'

import { LemonCard, LemonInput, LemonSegmentedButton, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { creditsToUsd, formatCreditCount } from '../../utils/credits'
import { CreditLimitUnit, replayScannerLogic } from '../replayScannerLogic'
import { MAX_CREDIT_LIMIT } from '../types'

interface ScannerCreditLimitProps {
    scannerId: string
}

export function ScannerCreditLimit({ scannerId }: ScannerCreditLimitProps): JSX.Element {
    const { creditLimitState } = useValues(replayScannerLogic({ id: scannerId }))
    const { setScannerValues, setCreditLimitUnit } = useActions(replayScannerLogic({ id: scannerId }))
    const {
        limit,
        unit,
        observationLimit,
        isOn,
        estimatedMonthly,
        creditsPerObservation,
        isBelowEstimate,
        cannotAffordOneScan,
        seedValue,
    } = creditLimitState
    const inObservations = unit === 'observations' && creditsPerObservation != null
    const toCredits = (amount: number): number =>
        inObservations ? Math.min(amount * creditsPerObservation, MAX_CREDIT_LIMIT) : amount

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
                            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                                <LemonSegmentedButton<CreditLimitUnit>
                                    size="small"
                                    value={inObservations ? 'observations' : 'credits'}
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
                                        value={(inObservations ? observationLimit : limit) ?? undefined}
                                        onChange={(v) =>
                                            // The toggle is materialized on edit too, so clearing a loaded limit blocks the save.
                                            setScannerValues({
                                                credit_limit_enabled: true,
                                                credit_limit:
                                                    v == null || !Number.isFinite(v)
                                                        ? null
                                                        : toCredits(Math.max(1, Math.round(v))),
                                            })
                                        }
                                        min={1}
                                        max={
                                            inObservations
                                                ? Math.floor(MAX_CREDIT_LIMIT / creditsPerObservation)
                                                : MAX_CREDIT_LIMIT
                                        }
                                        step={1}
                                        suffix={<span>{inObservations ? 'observations' : 'credits'}</span>}
                                    />
                                </div>
                                <span className="text-sm text-muted">
                                    {limit != null &&
                                        (inObservations
                                            ? `${formatCreditCount(limit)} (≈ ${creditsToUsd(limit)}) per period`
                                            : `≈ ${creditsToUsd(limit)} per period`)}
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
                            {inObservations && (
                                <div className="text-xs text-muted">
                                    If you change the model, the credit limit changes to keep the same number of
                                    observations.
                                </div>
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
