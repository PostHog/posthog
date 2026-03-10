import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { RuleList } from '../rules/RuleList'
import { ErrorTrackingRuleType } from '../rules/types'
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
        />
    )
}
