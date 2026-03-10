import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { RuleModal } from '../rules/RuleModal'
import { suppressionRuleModalLogic } from './suppressionRuleModalLogic'

export function SuppressionRuleModal(): JSX.Element {
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
        />
    )
}
