import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect, type LemonSelectOptions, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import type { ErrorTrackingIssueTagColor } from '~/queries/schema/schema-general'

import { IssueTag } from '../../../components/IssueTag/IssueTag'
import { ISSUE_TAG_COLORS, issueTagColor } from '../../../components/IssueTag/issueTagColors'
import { RuleModal } from '../rules/RuleModal'
import { TagRuleMatchBanner } from './TagRuleMatchBanner'
import { tagRuleModalLogic } from './tagRuleModalLogic'

function colorOptions(
    automaticColor: ErrorTrackingIssueTagColor
): LemonSelectOptions<ErrorTrackingIssueTagColor | null> {
    return [
        { value: null, label: <IssueTag label="Automatic" color={automaticColor} /> },
        ...ISSUE_TAG_COLORS.map((color) => ({
            value: color,
            label: <IssueTag label={capitalizeFirstLetter(color)} color={color} />,
        })),
    ]
}

export function TagRuleModal(): JSX.Element {
    const { rule, hasFilters, hasLabel } = useValues(tagRuleModalLogic)
    const { updateLabel, updateDescription, updateColor } = useActions(tagRuleModalLogic)
    const saveDisabledReason = !hasFilters ? 'Add at least one filter' : !hasLabel ? 'Add a tag' : undefined
    const previewLabel = rule.label.trim() || 'Tag'
    const automaticColor = issueTagColor(previewLabel, null)

    return (
        <RuleModal
            logic={tagRuleModalLogic}
            ruleLabel="tag"
            description="New issues get this tag when their first exception matches the filters. Once a day, other issues get it when an exception from the past day matches. Filters on the exception list check only the first exception. Deleting the rule removes the tag from every issue."
            pageKey="tag-rule-modal"
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
            saveDisabledReason={saveDisabledReason}
            leadingFields={
                <>
                    <div className="flex flex-wrap items-end gap-2">
                        <div className="min-w-48 flex-1">
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
                            <LemonLabel htmlFor="tag-rule-color" className="mb-2">
                                Color
                            </LemonLabel>
                            <LemonSelect
                                id="tag-rule-color"
                                data-attr="error-tracking-tag-rule-color"
                                value={rule.color}
                                onChange={updateColor}
                                options={colorOptions(automaticColor)}
                            />
                        </div>
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
                    <div className="flex flex-col items-start">
                        <LemonLabel className="mb-2">Preview</LemonLabel>
                        <Tooltip title={rule.description || undefined}>
                            <IssueTag
                                className="max-w-full"
                                tabIndex={rule.description ? 0 : undefined}
                                label={previewLabel}
                                color={rule.color}
                            />
                        </Tooltip>
                    </div>
                </>
            }
            extraFields={<TagRuleMatchBanner />}
        />
    )
}
