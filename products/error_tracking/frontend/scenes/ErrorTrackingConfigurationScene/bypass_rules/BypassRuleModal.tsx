import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { RuleModal } from '../rules/RuleModal'
import { bypassRuleModalLogic } from './bypassRuleModalLogic'

export function BypassRuleModal(): JSX.Element {
    return (
        <RuleModal
            logic={bypassRuleModalLogic}
            ruleLabel="bypass"
            description="Matching exceptions are always ingested, skipping rate limiting entirely."
            pageKey="bypass-rule-modal"
            width={800}
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.ErrorTrackingProperties,
                TaxonomicFilterGroupType.EventProperties,
            ]}
            showTestButton={false}
        />
    )
}
