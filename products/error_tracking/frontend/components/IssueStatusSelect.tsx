import {
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from 'lib/ui/quill'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { ISSUE_STATUS_OPTIONS } from '../utils'
import { getIssueStatusConfig, StatusIndicator } from './Indicators'

export const IssueStatusSelect = ({
    status,
    options = ISSUE_STATUS_OPTIONS,
    onChange,
    size = 'sm',
}: {
    status: ErrorTrackingIssue['status']
    options?: ErrorTrackingIssue['status'][]
    onChange: (status: ErrorTrackingIssue['status']) => void
    size?: 'sm' | 'default'
}): JSX.Element => {
    return (
        <Select
            value={status}
            onValueChange={(nextStatus: ErrorTrackingIssue['status'] | null) => {
                if (nextStatus && nextStatus !== status) {
                    onChange(nextStatus)
                }
            }}
        >
            <SelectTrigger size={size} className="gap-1" aria-label={`Status: ${getIssueStatusConfig(status).label}`}>
                <SelectValue>
                    <StatusIndicator status={status} size="xsmall" className="text-secondary" />
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                <SelectGroup>
                    <SelectGroupLabel className="py-1">Status</SelectGroupLabel>
                    {options.map((option) => (
                        <SelectItem key={option} value={option}>
                            <StatusIndicator status={option} size="xsmall" />
                        </SelectItem>
                    ))}
                </SelectGroup>
            </SelectContent>
        </Select>
    )
}
