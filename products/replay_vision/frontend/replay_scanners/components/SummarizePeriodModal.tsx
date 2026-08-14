import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { DateMappingOption } from '~/types'

import type { RunPreviewResponseApi, RunPreviewTierApi } from '../../generated/api.schemas'
import { formatCreditCount } from '../../utils/credits'
import { CoverageTierKey, FALLBACK_TIER_CAPS, scannerDigestLogic } from '../scannerDigestLogic'

// Day-scale presets: a period summary rolls up days or weeks of findings, unlike backfills where
// hour-scale re-scans matter.
const PERIOD_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    { key: 'Last 24 hours', values: ['-24h'] },
    { key: 'Last 7 days', values: ['-7d'] },
    { key: 'Last 14 days', values: ['-14d'] },
    { key: 'Last 30 days', values: ['-30d'] },
    { key: 'Last 90 days', values: ['-90d'] },
]

const TIER_KEYS: CoverageTierKey[] = ['standard', 'deep', 'complete']

const TIER_LABELS: Record<CoverageTierKey, string> = {
    standard: 'Standard',
    deep: 'Deep',
    complete: 'Complete',
}

function tierTooltip(key: CoverageTierKey, cap: number): string {
    return key === 'complete'
        ? `Summarize every observation in the period, up to ${humanFriendlyNumber(cap)}`
        : `Summarize an even sample of up to ${humanFriendlyNumber(cap)} observations`
}

function coverageSummary(preview: RunPreviewResponseApi, tier: RunPreviewTierApi): string {
    const total = preview.observation_count
    const noun = total === 1 ? 'observation' : 'observations'
    const scope =
        tier.covered_count < total
            ? `an even sample of ${humanFriendlyNumber(tier.covered_count)} of the ${humanFriendlyNumber(total)} ${noun}`
            : total === 1
              ? 'the 1 observation'
              : `all ${humanFriendlyNumber(total)} ${noun}`
    return `Summarizes ${scope} in this period for about ${formatCreditCount(tier.estimated_credits)}.`
}

/** Picks the observation window and coverage for a one-off digest run over a chosen period, e.g. a
 * whole backfill, instead of the digest's usual "everything since the last run". */
export function SummarizePeriodModal({
    scannerId,
    scannerName,
}: {
    scannerId: string
    scannerName: string
}): JSX.Element {
    const logic = scannerDigestLogic({ scannerId, scannerName })
    const {
        periodModalOpen,
        periodDateFrom,
        periodDateTo,
        summarizingPeriod,
        runInProgress,
        coverageTier,
        runPreview,
        runPreviewLoading,
    } = useValues(logic)
    const { closePeriodModal, setPeriodRange, summarizePeriod, setCoverageTier } = useActions(logic)

    const selectedTier = runPreview?.tiers.find((t) => t.key === coverageTier)
    const emptyPeriod = !runPreviewLoading && runPreview?.observation_count === 0

    return (
        <LemonModal
            isOpen={periodModalOpen}
            onClose={closePeriodModal}
            title="Summarize a period"
            description="Generate a one-off summary of everything this scanner found in a period. The recurring digest and its schedule stay unchanged."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closePeriodModal} data-attr="vision-digest-period-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={summarizePeriod}
                        loading={summarizingPeriod}
                        disabledReason={
                            runInProgress
                                ? 'A run is already in progress'
                                : emptyPeriod
                                  ? 'No observations in this period'
                                  : undefined
                        }
                        data-attr="vision-digest-period-generate"
                    >
                        Generate summary
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <DateFilter
                    dateFrom={periodDateFrom}
                    dateTo={periodDateTo}
                    dateOptions={PERIOD_DATE_OPTIONS}
                    onChange={(dateFrom, dateTo) => setPeriodRange(dateFrom, dateTo)}
                    data-attr="vision-digest-period-date-filter"
                />
                <div className="flex flex-col gap-1.5">
                    <span className="font-semibold text-sm">Coverage</span>
                    <LemonSegmentedButton
                        value={coverageTier}
                        onChange={(tier) => setCoverageTier(tier)}
                        size="small"
                        fullWidth
                        options={TIER_KEYS.map((key) => {
                            const tier = runPreview?.tiers.find((t) => t.key === key)
                            const cap = tier?.max_observations ?? FALLBACK_TIER_CAPS[key]
                            return {
                                value: key,
                                label: tier ? (
                                    <span className="flex items-baseline gap-1.5">
                                        {TIER_LABELS[key]}
                                        <span className="text-muted text-xs font-normal">
                                            {formatCreditCount(tier.estimated_credits)}
                                        </span>
                                    </span>
                                ) : (
                                    TIER_LABELS[key]
                                ),
                                tooltip: tierTooltip(key, cap),
                                'data-attr': `vision-digest-period-coverage-${key}`,
                            }
                        })}
                    />
                    <p className="text-muted text-xs mb-0">
                        {runPreviewLoading ? (
                            <span className="flex items-center gap-1">
                                <Spinner /> Counting observations in this period…
                            </span>
                        ) : emptyPeriod ? (
                            'No observations in this period. Pick a different range.'
                        ) : runPreview && selectedTier ? (
                            coverageSummary(runPreview, selectedTier)
                        ) : (
                            'When a period holds more observations than the coverage cap, an even sample across the period is summarized, and the summary says so.'
                        )}
                    </p>
                </div>
            </div>
        </LemonModal>
    )
}
