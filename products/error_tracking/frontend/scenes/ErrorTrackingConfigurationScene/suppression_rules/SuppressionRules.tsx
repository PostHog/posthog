import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { RuleList } from '../rules/RuleList'
import { ErrorTrackingRuleType, ErrorTrackingSuppressionRule } from '../rules/types'
import { EvaluationIndicator, SamplingRateIndicator, getEvalMode } from './EvaluationIndicator'
import { SuppressionRuleModal } from './SuppressionRuleModal'
import { suppressionRuleModalLogic } from './suppressionRuleModalLogic'

export function SuppressionRules(): JSX.Element {
    return (
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
                    <EvaluationIndicator mode={getEvalMode(rule.filters)} />
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
}
