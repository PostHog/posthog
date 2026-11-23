import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect, type LemonSelectOptions, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import type { ErrorTrackingIssueTagColor } from '~/queries/schema/schema-general'

import { IssueTag } from '../../../components/IssueTag/IssueTag'
import { ISSUE_TAG_COLOR_LABELS, issueTagColor } from '../../../components/IssueTag/issueTagColors'
import { RuleModal } from '../rules/RuleModal'
import { TagRuleMatchBanner } from './TagRuleMatchBanner'
import { tagRuleModalLogic } from './tagRuleModalLogic'

const AUTOMATIC_COLOR_LABEL = 'Automatic'

function colorOptions(
    automaticColor: ErrorTrackingIssueTagColor
): LemonSelectOptions<ErrorTrackingIssueTagColor | null> {
    return [
        {
            value: null,
            label: AUTOMATIC_COLOR_LABEL,
            labelInMenu: <IssueTag label={AUTOMATIC_COLOR_LABEL} color={automaticColor} />,
        },
        ...(Object.keys(ISSUE_TAG_COLOR_LABELS) as ErrorTrackingIssueTagColor[]).map((color) => ({
            value: color,
            label: ISSUE_TAG_COLOR_LABELS[color],
            labelInMenu: <IssueTag label={ISSUE_TAG_COLOR_LABELS[color]} color={color} />,
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
            description="New issues get this tag when their first exception matches the filters. The rule applies to new issues only. Deleting it removes the tag from every issue."
            pageKey="tag-rule-modal"
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
            saveDisabledReason={saveDisabledReason}
            extraFields={
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
                                renderButtonContent={(leaf) =>
                                    leaf?.value ? (
                                        <IssueTag label={ISSUE_TAG_COLOR_LABELS[leaf.value]} color={leaf.value} />
                                    ) : (
                                        <IssueTag label={AUTOMATIC_COLOR_LABEL} color={automaticColor} />
                                    )
                                }
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
                            <IssueTag tabIndex={0} label={previewLabel} color={rule.color} />
                        </Tooltip>
                    </div>
                    <TagRuleMatchBanner />
                </>
            }
        />
    )
}
