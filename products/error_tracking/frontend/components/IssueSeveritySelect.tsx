import {
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Spinner,
} from 'lib/ui/quill'

import { ISSUE_SEVERITY_OPTIONS, IssueSeverityTag, issueSeverityLabel, type IssueSeverity } from './IssueSeverityTag'

type IssueSeveritySelectProps = {
    severity: IssueSeverity | null | undefined
    onChange: (severity: IssueSeverity) => void
    loading?: boolean
    size?: 'sm' | 'default'
}

export function IssueSeveritySelect({
    severity,
    onChange,
    loading = false,
    size = 'sm',
}: IssueSeveritySelectProps): JSX.Element {
    return (
        <Select
            value={severity ?? null}
            onValueChange={(nextSeverity: IssueSeverity | null) => {
                if (nextSeverity && nextSeverity !== severity) {
                    onChange(nextSeverity)
                }
            }}
        >
            <SelectTrigger
                disabled={loading}
                data-loading={loading || undefined}
                aria-busy={loading || undefined}
                size={size}
                className="gap-1 disabled:opacity-100"
                aria-label={`Severity: ${issueSeverityLabel(severity)}`}
                data-attr="error-tracking-issue-severity"
            >
                <SelectValue>
                    <IssueSeverityTag severity={severity} />
                </SelectValue>
                {loading && <Spinner />}
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                <SelectGroup>
                    <SelectGroupLabel className="py-1">Severity</SelectGroupLabel>
                    {ISSUE_SEVERITY_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            <IssueSeverityTag severity={option.value} />
                        </SelectItem>
                    ))}
                </SelectGroup>
            </SelectContent>
        </Select>
    )
}
