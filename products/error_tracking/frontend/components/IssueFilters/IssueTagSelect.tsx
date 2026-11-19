import { LemonSelect } from '@posthog/lemon-ui'

import type { ErrorTrackingIssueTagFilter } from '~/queries/schema/schema-general'

import type { ErrorTrackingIssueTagDefinitionApi } from '../../generated/api.schemas'

function appliedOptionText(applied: boolean): string {
    return applied ? 'Has label' : "Doesn't have label"
}

// LemonSelect takes only primitive values. The applied part never holds a colon, so the last colon splits the two.
function toOptionValue({ key, applied }: ErrorTrackingIssueTagFilter): string {
    return `${key}:${applied}`
}

function fromOptionValue(optionValue: string): ErrorTrackingIssueTagFilter {
    const separator = optionValue.lastIndexOf(':')
    return { key: optionValue.slice(0, separator), applied: optionValue.slice(separator + 1) === 'true' }
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
    const buttonText = issueTag ? `${appliedOptionText(issueTag.applied)}: ${labelOf(issueTag.key)}` : 'Any label'

    return (
        <LemonSelect
            allowClear
            size="small"
            aria-label={`Label filter: ${buttonText}`}
            data-attr="error-tracking-issue-tag-filter"
            loading={loading}
            value={issueTag ? toOptionValue(issueTag) : null}
            onChange={(optionValue) => onChange(optionValue ? fromOptionValue(optionValue) : null)}
            options={definitions.map((definition) => ({
                title: definition.label,
                options: [true, false].map((applied) => ({
                    value: toOptionValue({ key: definition.key, applied }),
                    label: appliedOptionText(applied),
                })),
            }))}
            renderButtonContent={() => buttonText}
        />
    )
}
