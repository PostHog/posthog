import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { BuiltInFilters } from '../built_in_filters/BuiltInFilters'
import { RuleList } from '../rules/RuleList'
import { ErrorTrackingRuleType, ErrorTrackingSuppressionRule } from '../rules/types'
import { EvaluationIndicator, SamplingRateIndicator, getEvalMode } from './EvaluationIndicator'
import { SuppressionRuleModal } from './SuppressionRuleModal'
import { suppressionRuleModalLogic } from './suppressionRuleModalLogic'

export function SuppressionRules(): JSX.Element {
    const hasAutomaticRules = useFeatureFlag('ERROR_TRACKING_BUILT_IN_FILTERS')

    const manualRules = (
        <RuleList
            ruleType={ErrorTrackingRuleType.Suppression}
            modalLogic={suppressionRuleModalLogic}
            modal={<SuppressionRuleModal />}
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.ErrorTrackingProperties,
                TaxonomicFilterGroupType.EventProperties,
            ]}
            pageKeyPrefix="suppression-rule"
            renderCardHeaderExtra={(rule: ErrorTrackingSuppressionRule) => (
                <>
                    <span className="text-muted">·</span>
                    <EvaluationIndicator mode={getEvalMode(rule.filters)} samplingRate={rule.sampling_rate} />
                    {rule.sampling_rate < 1.0 && (
                        <>
                            <span className="text-muted">·</span>
                            <SamplingRateIndicator samplingRate={rule.sampling_rate} />
                        </>
                    )}
                </>
            )}
        />
    )

    if (!hasAutomaticRules) {
        return manualRules
    }

    return (
        <div className="space-y-8">
            <div className="space-y-4">
                <div>
                    <h3 className="font-semibold text-base mb-1">Automatic suppression rules</h3>
                    <p className="text-muted-foreground">
                        PostHog maintains these rules for common exceptions that you usually can't act on, and keeps
                        them up to date.
                    </p>
                </div>
                <BuiltInFilters />
            </div>
            <div className="space-y-4">
                <div>
                    <h3 className="font-semibold text-base mb-1">Manual suppression rules</h3>
                    <p className="text-muted-foreground">Rules that you create and edit.</p>
                </div>
                {manualRules}
            </div>
        </div>
    )
}
