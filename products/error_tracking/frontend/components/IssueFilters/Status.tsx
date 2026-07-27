import { useActions, useValues } from 'kea'

import { LemonSelect, type LemonSelectProps } from '@posthog/lemon-ui'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { LabelIndicator, StatusIndicator } from '../Indicators'
import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'

export type ErrorTrackingStatusSelectValue = ErrorTrackingIssue['status'] | 'all'

const STATUS_OPTIONS: ErrorTrackingStatusSelectValue[] = ['all', 'active', 'resolved', 'suppressed']

function statusOptionLabel(key: ErrorTrackingStatusSelectValue): JSX.Element {
    if (key === 'all') {
        return <LabelIndicator intent="muted" label="All" size="small" />
    }
    return <StatusIndicator status={key} size="small" withTooltip="right" />
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

    return <ErrorTrackingStatusSelect value={status ?? 'active'} onChange={(value) => setStatus(value)} />
}
