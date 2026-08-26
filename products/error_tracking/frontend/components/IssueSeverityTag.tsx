import { LemonTag, type LemonTagType } from '@posthog/lemon-ui'

import type { ErrorTrackingQueryIssueSeverity } from '~/queries/schema/schema-general'

export type IssueSeverity = ErrorTrackingQueryIssueSeverity

export const ISSUE_SEVERITY_OPTIONS: { label: string; value: IssueSeverity }[] = [
    { label: 'Low', value: 'low' },
    { label: 'Medium', value: 'medium' },
    { label: 'High', value: 'high' },
    { label: 'Critical', value: 'critical' },
]

export function issueSeverityTagType(severity: IssueSeverity | null | undefined): LemonTagType {
    if (severity === 'critical') {
        return 'danger'
    }
    if (severity === 'high') {
        return 'warning'
    }
    if (!severity) {
        return 'muted'
    }
    return 'default'
}

export function issueSeverityLabel(severity: IssueSeverity | null | undefined): string {
    if (!severity) {
        return 'No severity'
    }
    return ISSUE_SEVERITY_OPTIONS.find((option) => option.value === severity)?.label ?? severity
}

export function IssueSeverityTag({ severity }: { severity: IssueSeverity | null | undefined }): JSX.Element {
    return (
        <LemonTag type={issueSeverityTagType(severity)} size="small">
            {issueSeverityLabel(severity)}
        </LemonTag>
    )
}
