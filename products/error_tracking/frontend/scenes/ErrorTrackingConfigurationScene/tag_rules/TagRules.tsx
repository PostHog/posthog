import { LemonTag } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { RuleList } from '../rules/RuleList'
import { ErrorTrackingRuleType, ErrorTrackingTagRule } from '../rules/types'
import { TagRuleModal } from './TagRuleModal'
import { tagRuleModalLogic } from './tagRuleModalLogic'

export function TagRules(): JSX.Element {
    return (
        <RuleList
            ruleType={ErrorTrackingRuleType.Tag}
            modalLogic={tagRuleModalLogic}
            modal={<TagRuleModal />}
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
            pageKeyPrefix="tag-rule"
            description={
                <p>
                    Label new issues based on their exception properties. Each rule adds its label to every new issue
                    whose first exception matches its filters, so one issue can get several labels. Rules apply to new
                    issues only. Deleting a rule removes its label from every issue.
                </p>
            }
            renderCardHeaderExtra={(rule: ErrorTrackingTagRule) => (
                <>
                    <span className="text-muted">·</span>
                    <LemonTag className="max-w-40" title={rule.label}>
                        <span className="truncate">{rule.label}</span>
                    </LemonTag>
                </>
            )}
        />
    )
}
