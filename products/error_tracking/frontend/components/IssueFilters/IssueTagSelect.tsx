import { LemonSelect } from '@posthog/lemon-ui'

import type { ErrorTrackingIssueTagFilter, ErrorTrackingIssueTagFilterValue } from '~/queries/schema/schema-general'

import type { ErrorTrackingIssueTagDefinitionApi } from '../../generated/api.schemas'
import { ISSUE_TAG_ANSWER_LABELS } from '../IssueQueryOptions/issueQueryOptionsLogic'

const ANSWERS = Object.keys(ISSUE_TAG_ANSWER_LABELS) as ErrorTrackingIssueTagFilterValue[]

// LemonSelect takes only primitive values. The answer never holds a colon, so the last colon splits the two.
function toOptionValue({ key, value }: ErrorTrackingIssueTagFilter): string {
    return `${key}:${value}`
}

function fromOptionValue(optionValue: string): ErrorTrackingIssueTagFilter {
    const separator = optionValue.lastIndexOf(':')
    return {
        key: optionValue.slice(0, separator),
        value: optionValue.slice(separator + 1) as ErrorTrackingIssueTagFilterValue,
    }
}

export function IssueTagSelect({
    definitions,
    loading,
    issueTag,
    onChange,
}: {
    definitions: Pick<ErrorTrackingIssueTagDefinitionApi, 'key' | 'label'>[]
    loading: boolean
    issueTag: ErrorTrackingIssueTagFilter | null
    onChange: (issueTag: ErrorTrackingIssueTagFilter | null) => void
}): JSX.Element {
    const labelOf = (key: string): string => definitions.find((definition) => definition.key === key)?.label ?? key
    const buttonText = issueTag ? `${labelOf(issueTag.key)}: ${ISSUE_TAG_ANSWER_LABELS[issueTag.value]}` : 'Any tag'

    return (
        <LemonSelect
            allowClear
            size="small"
            aria-label={`Tag filter: ${buttonText}`}
            data-attr="error-tracking-issue-tag-filter"
            loading={loading}
            value={issueTag ? toOptionValue(issueTag) : null}
            onChange={(optionValue) => onChange(optionValue ? fromOptionValue(optionValue) : null)}
            options={definitions.map((definition) => ({
                title: definition.label,
                options: ANSWERS.map((answer) => ({
                    value: toOptionValue({ key: definition.key, value: answer }),
                    label: ISSUE_TAG_ANSWER_LABELS[answer],
                })),
            }))}
            renderButtonContent={() => buttonText}
        />
    )
}
