import { useActions, useValues } from 'kea'

import { LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { RuleModal } from '../rules/RuleModal'
import { TagRuleMatchBanner } from './TagRuleMatchBanner'
import { tagRuleModalLogic } from './tagRuleModalLogic'

export function TagRuleModal(): JSX.Element {
    const { rule, hasFilters, hasLabel } = useValues(tagRuleModalLogic)
    const { updateLabel, updateDescription } = useActions(tagRuleModalLogic)
    const saveDisabledReason = !hasFilters ? 'Add at least one filter' : !hasLabel ? 'Add a tag' : undefined

    return (
        <RuleModal
            logic={tagRuleModalLogic}
            ruleLabel="tag"
            description="New issues get this tag when their first exception matches the filters. The rule applies to new issues only. Deleting it removes the tag from every issue."
            pageKey="tag-rule-modal"
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
            saveDisabledReason={saveDisabledReason}
            extraFields={
                <>
                    <div>
                        <LemonLabel htmlFor="tag-rule-label" className="mb-2">
                            Tag
                        </LemonLabel>
                        <LemonInput
                            id="tag-rule-label"
                            fullWidth
                            value={rule.label}
                            maxLength={128}
                            onChange={updateLabel}
                        />
                    </div>
                    <div>
                        <LemonLabel htmlFor="tag-rule-description" className="mb-2" showOptional>
                            Description
                        </LemonLabel>
                        <LemonTextArea
                            id="tag-rule-description"
                            value={rule.description}
                            placeholder="What the tag means. People see it when they hover the tag on an issue."
                            onChange={updateDescription}
                        />
                    </div>
                    <TagRuleMatchBanner />
                </>
            }
        />
    )
}
