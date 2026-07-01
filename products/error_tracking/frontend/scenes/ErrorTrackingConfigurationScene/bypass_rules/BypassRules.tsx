import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { RuleList } from '../rules/RuleList'
import { ErrorTrackingRuleType } from '../rules/types'
import { BypassRuleModal } from './BypassRuleModal'
import { bypassRuleModalLogic } from './bypassRuleModalLogic'

export function BypassRules(): JSX.Element {
    return (
        <RuleList
            ruleType={ErrorTrackingRuleType.Bypass}
            modalLogic={bypassRuleModalLogic}
            modal={<BypassRuleModal />}
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.ErrorTrackingProperties,
                TaxonomicFilterGroupType.EventProperties,
            ]}
            pageKeyPrefix="bypass-rule"
        />
    )
}
