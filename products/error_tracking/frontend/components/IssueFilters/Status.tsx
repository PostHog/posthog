import { useActions, useValues } from 'kea'

import { LemonSelect, type LemonSelectProps } from '@posthog/lemon-ui'

import { Dot, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from 'lib/ui/quill'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { ISSUE_STATUS_CONFIG, IssueStatusDot, LabelIndicator, StatusIndicator } from '../Indicators'
import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'

export type ErrorTrackingStatusSelectValue = ErrorTrackingIssue['status'] | 'all'

const STATUS_OPTIONS: ErrorTrackingStatusSelectValue[] = ['all', 'active', 'resolved', 'suppressed']

function statusOptionLabel(key: ErrorTrackingStatusSelectValue): JSX.Element {
    if (key === 'all') {
        return <LabelIndicator intent="muted" label="All" size="small" />
    }
    return <StatusIndicator status={key} size="small" withTooltip="right" />
}

function quillStatusOptionLabel(key: ErrorTrackingStatusSelectValue): JSX.Element {
    if (key === 'all') {
        return (
            <span className="flex items-center gap-2">
                <Dot className="!border-0 !p-0" />
                All
            </span>
        )
    }

    return (
        <span className="flex items-center gap-2">
            <IssueStatusDot status={key} />
            {ISSUE_STATUS_CONFIG[key].label}
        </span>
    )
}

type ErrorTrackingStatusSelectProps = {
    value: ErrorTrackingStatusSelectValue
    onChange: (value: ErrorTrackingStatusSelectValue) => void
} & Pick<LemonSelectProps<ErrorTrackingStatusSelectValue>, 'fullWidth' | 'size' | 'disabled' | 'disabledReason'>

export function ErrorTrackingStatusSelect({
    value,
    onChange,
    fullWidth,
    size = 'small',
    disabled,
    disabledReason,
}: ErrorTrackingStatusSelectProps): JSX.Element {
    return (
        <LemonSelect
            fullWidth={fullWidth}
            size={size}
            disabled={disabled}
            disabledReason={disabledReason}
            value={value}
            onChange={(next) => {
                if (next) {
                    onChange(next)
                }
            }}
            placeholder="Select status"
            options={STATUS_OPTIONS.map((key) => ({
                value: key,
                label: statusOptionLabel(key),
            }))}
        />
    )
}

/** Issues tab filter bar — wires shared select to issueQueryOptionsLogic. */
export const StatusFilter = (): JSX.Element => {
    const { status } = useValues(issueQueryOptionsLogic)
    const { setStatus } = useActions(issueQueryOptionsLogic)
    const value = status ?? 'active'

    return (
        <Select value={value} onValueChange={(nextValue) => setStatus(nextValue as ErrorTrackingStatusSelectValue)}>
            <SelectTrigger size="default">
                <SelectValue>{quillStatusOptionLabel(value)}</SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                {STATUS_OPTIONS.map((option) => (
                    <SelectItem key={option} value={option}>
                        {quillStatusOptionLabel(option)}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
