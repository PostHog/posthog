import { LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { creditsToUsd, formatCreditCount } from '../../utils/credits'
import type { GoalSpendChoice } from '../replayScannerLogic'

export type ScannerCreditCap = 'free' | 'cap'

export interface ScannerSpendChoiceFieldsProps {
    spendChoice: GoalSpendChoice
    freeCreditsLeft: number | null
    budget: number | null
    onCreditCapChange: (cap: ScannerCreditCap) => void
    onBudgetChange: (budget: number | null) => void
    /** Prefix for the fields' data-attrs, so each entry point's autocapture stays separate. */
    dataAttrPrefix: string
}

/** The "free credits only or a monthly cap" choice that the in-place scanner entry points share. */
export function ScannerSpendChoiceFields({
    spendChoice,
    freeCreditsLeft,
    budget,
    onCreditCapChange,
    onBudgetChange,
    dataAttrPrefix,
}: ScannerSpendChoiceFieldsProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
            <span className="text-sm font-semibold">Do you want to set a credit cap for this scanner?</span>
            <LemonSegmentedButton<ScannerCreditCap>
                size="small"
                value={spendChoice.mode === 'free' ? 'free' : 'cap'}
                onChange={onCreditCapChange}
                options={[
                    {
                        value: 'free',
                        label: 'No, use free credits only',
                        disabledReason: spendChoice.freeDisabledReason ?? undefined,
                        'data-attr': `${dataAttrPrefix}-spend-free`,
                    },
                    { value: 'cap', label: 'Yes, set a cap', 'data-attr': `${dataAttrPrefix}-spend-cap` },
                ]}
            />
            {spendChoice.mode === 'free' ? (
                <div className="text-xs text-secondary">
                    The Replay vision scanner only uses your free monthly credits
                    {/* Its own span, so page translation cannot strand the changing balance. */}
                    <span>{freeCreditsLeft != null ? ` (${formatCreditCount(freeCreditsLeft)} left)` : ''}</span>. It
                    pauses when they run out, so it never adds to your bill.
                </div>
            ) : (
                <div className="flex flex-wrap items-center gap-2">
                    <LemonInput
                        aria-label="Monthly credit cap"
                        type="number"
                        min={1}
                        value={budget ?? undefined}
                        onChange={(value) => onBudgetChange(value ?? null)}
                        suffix={<span className="text-secondary">credits a month</span>}
                        size="small"
                        className="w-56"
                        data-attr={`${dataAttrPrefix}-budget`}
                    />
                    {budget != null && budget > 0 ? (
                        <span className="text-xs text-secondary">
                            ≈ <span translate="no">{creditsToUsd(budget)}</span> a month
                        </span>
                    ) : null}
                </div>
            )}
        </div>
    )
}
