import { useActions, useValues } from 'kea'

import { LemonBadge, LemonSelect, type LemonSelectProps } from '@posthog/lemon-ui'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { Intent, LabelIndicator, STATUS_INTENT, STATUS_LABEL, StatusIndicator } from '../Indicators'
import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'

export type ErrorTrackingStatusSelectValue = ErrorTrackingIssue['status'] | 'all'

export const STATUS_OPTIONS: ErrorTrackingStatusSelectValue[] = ['all', 'active', 'resolved', 'suppressed']

export function statusOptionLabel(key: ErrorTrackingStatusSelectValue): JSX.Element {
    if (key === 'all') {
        return <LabelIndicator intent="muted" label="All" size="small" />
    }
    return <StatusIndicator status={key} size="small" withTooltip="right" />
}

const STATUS_DESCRIPTION: Record<ErrorTrackingStatusSelectValue, string> = {
    all: 'Show issues with any status',
    active: 'Ongoing issues that need attention',
    resolved: 'Fixed — reactivates if it happens again',
    suppressed: 'Ignored — new occurrences are dropped',
    archived: 'Set aside and hidden from the list',
    pending_release: 'Resolved in an upcoming release',
}

/** Two-line option: a status dot, then the label (prominent) over a muted description. No tooltip/help cursor. */
export function statusOptionLabelWithDescription(key: ErrorTrackingStatusSelectValue): JSX.Element {
    const intent: Intent = key === 'all' ? 'muted' : STATUS_INTENT[key]
    const label = key === 'all' ? 'All' : STATUS_LABEL[key]

    return (
        <div className="flex items-start gap-2 py-1">
            <LemonBadge status={intent} size="small" className="mt-1 shrink-0" />
            <div className="flex flex-col gap-0.5 text-left">
                <span className="text-sm font-semibold leading-tight">{label}</span>
                <span className="text-xs leading-tight text-secondary">{STATUS_DESCRIPTION[key]}</span>
            </div>
        </div>
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

    return <ErrorTrackingStatusSelect value={status ?? 'active'} onChange={(value) => setStatus(value)} />
}
