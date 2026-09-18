import { useActions, useValues } from 'kea'

import {
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from 'lib/ui/quill'

import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { ISSUE_SEVERITY_OPTIONS, IssueSeverityTag, type IssueSeverity } from '../IssueSeverityTag'

const ALL_SEVERITIES_VALUE = 'all'

type SeverityFilterValue = IssueSeverity | typeof ALL_SEVERITIES_VALUE

function SeverityFilterLabel({ severity }: { severity: IssueSeverity | null }): JSX.Element {
    return <IssueSeverityTag severity={severity} label={severity ? undefined : 'Any severity'} />
}

export function SeverityFilter(): JSX.Element {
    const { severity } = useValues(issueQueryOptionsLogic)
    const { setSeverity } = useActions(issueQueryOptionsLogic)
    const value: SeverityFilterValue = severity ?? ALL_SEVERITIES_VALUE

    return (
        <Select
            value={value}
            onValueChange={(nextValue: SeverityFilterValue | null) => {
                if (nextValue) {
                    setSeverity(nextValue === ALL_SEVERITIES_VALUE ? null : nextValue)
                }
            }}
        >
            <SelectTrigger size="default" aria-label="Severity filter" data-attr="error-tracking-severity-filter">
                <SelectValue>
                    <SeverityFilterLabel severity={severity} />
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                <SelectGroup>
                    <SelectGroupLabel className="py-1">Severity</SelectGroupLabel>
                    <SelectItem value={ALL_SEVERITIES_VALUE}>
                        <SeverityFilterLabel severity={null} />
                    </SelectItem>
                    {ISSUE_SEVERITY_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            <SeverityFilterLabel severity={option.value} />
                        </SelectItem>
                    ))}
                </SelectGroup>
            </SelectContent>
        </Select>
    )
}
