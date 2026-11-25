import { useActions, useValues } from 'kea'

import { LemonSlider } from '@posthog/lemon-ui'
import { Field, FieldDescription, FieldLabel, Slider, Text } from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { UniversalFiltersGroup } from '~/types'

import { RuleModal } from '../rules/RuleModal'
import { ErrorTrackingSuppressionRule } from '../rules/types'
import { EvaluationIndicator, getEvalMode } from './EvaluationIndicator'
import { suppressionRuleModalLogic } from './suppressionRuleModalLogic'

export function SuppressionRuleModal(): JSX.Element {
    const { rule } = useValues(suppressionRuleModalLogic)
    const { updateSamplingRate } = useActions(suppressionRuleModalLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const evalMode = getEvalMode(rule.filters as UniversalFiltersGroup)
    const samplingPercent = Math.round((rule as ErrorTrackingSuppressionRule).sampling_rate * 100)

    return (
        <RuleModal
            logic={suppressionRuleModalLogic}
            ruleLabel="suppression"
            description="Matching exceptions will be dropped before they create issues."
            pageKey="suppression-rule-modal"
            width={800}
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.ErrorTrackingProperties,
                TaxonomicFilterGroupType.EventProperties,
            ]}
            suffix={(issuesLink, dateRangeLabel) => (
                <>
                    across {issuesLink} would have been suppressed in the last {dateRangeLabel}
                </>
            )}
            filtersOptional
            filterLabels={
                <EvaluationIndicator
                    mode={evalMode}
                    samplingRate={(rule as ErrorTrackingSuppressionRule).sampling_rate}
                />
            }
            samplingRate={(rule as ErrorTrackingSuppressionRule).sampling_rate}
            extraFields={
                todayRailNav ? (
                    <Field>
                        <div className="flex items-center justify-between gap-2">
                            <FieldLabel>Sampling rate</FieldLabel>
                            <Text size="sm" weight="semibold" render={<span className="m-0" />} translate="no">
                                {samplingPercent}%
                            </Text>
                        </div>
                        <FieldDescription>
                            Percentage of matching exceptions to suppress. Set to 100% to suppress all.
                        </FieldDescription>
                        <Slider
                            aria-label="Sampling rate"
                            min={0}
                            max={100}
                            step={1}
                            value={samplingPercent}
                            onValueChange={(value) =>
                                updateSamplingRate((Array.isArray(value) ? value[0] : value) / 100)
                            }
                        />
                    </Field>
                ) : (
                    <div>
                        <div className="flex items-center justify-between mb-1">
                            <span className="font-semibold text-sm">Sampling rate</span>
                            <span className="text-sm font-semibold">{samplingPercent}%</span>
                        </div>
                        <p className="text-secondary text-xs mb-2">
                            Percentage of matching exceptions to suppress. Set to 100% to suppress all.
                        </p>
                        <LemonSlider
                            min={0}
                            max={100}
                            step={1}
                            value={samplingPercent}
                            onChange={(value) => updateSamplingRate(value / 100)}
                        />
                    </div>
                )
            }
        />
    )
}
