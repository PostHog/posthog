import clsx from 'clsx'

import type { ErrorTrackingQueryIssueSeverity } from '~/queries/schema/schema-general'

export type IssueSeverity = ErrorTrackingQueryIssueSeverity

export const ISSUE_SEVERITY_OPTIONS: { label: string; value: IssueSeverity }[] = [
    { label: 'Low', value: 'low' },
    { label: 'Medium', value: 'medium' },
    { label: 'High', value: 'high' },
    { label: 'Critical', value: 'critical' },
]

export function issueSeverityLabel(severity: IssueSeverity | null | undefined): string {
    if (!severity) {
        return 'No severity'
    }
    return ISSUE_SEVERITY_OPTIONS.find((option) => option.value === severity)?.label ?? severity
}

function issueSeverityColor(severity: IssueSeverity | null | undefined): string {
    if (severity === 'critical') {
        return 'text-danger'
    }
    if (severity === 'high') {
        return 'text-warning'
    }
    if (severity === 'medium') {
        return 'text-purple'
    }
    return 'text-muted'
}

function issueSeverityIcon(severity: IssueSeverity | null | undefined): JSX.Element {
    const activeBars = severity ? ISSUE_SEVERITY_OPTIONS.findIndex((option) => option.value === severity) + 1 : 0

    return (
        <svg aria-hidden viewBox="0 0 11 9" className="size-3">
            {[2.5, 4.5, 6.5, 8.5].map((height, index) => (
                <rect
                    key={height}
                    x={index * 3}
                    y={9 - height}
                    width="2"
                    height={height}
                    rx="0.5"
                    fill="currentColor"
                    opacity={index < activeBars ? 1 : 0.2}
                />
            ))}
        </svg>
    )
}

export function IssueSeverityTag({
    severity,
    label,
}: {
    severity: IssueSeverity | null | undefined
    label?: string
}): JSX.Element {
    return (
        <span className={clsx('inline-flex items-center gap-1 text-xs font-medium', issueSeverityColor(severity))}>
            {issueSeverityIcon(severity)}
            {label ?? issueSeverityLabel(severity)}
        </span>
    )
}
