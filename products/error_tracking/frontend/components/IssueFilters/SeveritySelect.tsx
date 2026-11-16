import {
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from 'lib/ui/quill'

import { ISSUE_SEVERITY_OPTIONS, IssueSeverityTag, type IssueSeverity } from '../IssueSeverityTag'

const ALL_SEVERITIES_VALUE = 'all'

type SeveritySelectValue = IssueSeverity | typeof ALL_SEVERITIES_VALUE

function SeverityLabel({ severity }: { severity: IssueSeverity | null }): JSX.Element {
    return <IssueSeverityTag severity={severity} label={severity ? undefined : 'Any severity'} />
}

export function SeveritySelect({
    severity,
    onChange,
}: {
    severity: IssueSeverity | null
    onChange: (severity: IssueSeverity | null) => void
}): JSX.Element {
    const value: SeveritySelectValue = severity ?? ALL_SEVERITIES_VALUE

    return (
        <Select
            value={value}
            onValueChange={(nextValue: SeveritySelectValue | null) => {
                if (nextValue) {
                    onChange(nextValue === ALL_SEVERITIES_VALUE ? null : nextValue)
                }
            }}
        >
            <SelectTrigger size="default" aria-label="Severity filter" data-attr="error-tracking-severity-filter">
                <SelectValue>
                    <SeverityLabel severity={severity} />
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                <SelectGroup>
                    <SelectGroupLabel className="py-1">Severity</SelectGroupLabel>
                    <SelectItem value={ALL_SEVERITIES_VALUE}>
                        <SeverityLabel severity={null} />
                    </SelectItem>
                    {ISSUE_SEVERITY_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            <SeverityLabel severity={option.value} />
                        </SelectItem>
                    ))}
                </SelectGroup>
            </SelectContent>
        </Select>
    )
}
