import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { BuiltInFilters } from '../built_in_filters/BuiltInFilters'
import { QuillConfigurationSubsection } from '../QuillConfigurationSubsection'
import { RuleList } from '../rules/RuleList'
import { ErrorTrackingRuleType, ErrorTrackingSuppressionRule } from '../rules/types'
import { EvaluationIndicator, SamplingRateIndicator, getEvalMode } from './EvaluationIndicator'
import { SuppressionRuleModal } from './SuppressionRuleModal'
import { suppressionRuleModalLogic } from './suppressionRuleModalLogic'

export function SuppressionRules(): JSX.Element {
    const hasAutomaticRules = useFeatureFlag('ERROR_TRACKING_BUILT_IN_FILTERS')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const separatorClassName = todayRailNav ? 'text-muted-foreground' : 'text-muted'

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
                    <span className={separatorClassName}>·</span>
                    <EvaluationIndicator mode={getEvalMode(rule.filters)} samplingRate={rule.sampling_rate} />
                    {rule.sampling_rate < 1.0 && (
                        <>
                            <span className={separatorClassName}>·</span>
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

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-8">
                <QuillConfigurationSubsection
                    title="Automatic suppression rules"
                    description="PostHog maintains these rules for common exceptions that you usually can't act on, and keeps them up to date."
                >
                    <BuiltInFilters />
                </QuillConfigurationSubsection>
                <QuillConfigurationSubsection
                    title="Manual suppression rules"
                    description="Rules that you create and edit."
                >
                    {manualRules}
                </QuillConfigurationSubsection>
            </div>
        )
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
