import { LemonBadge, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { FeedbackStatus } from '../types'

type StatusOption = FeedbackStatus | 'all'

const STATUS_LABELS: Record<StatusOption, { label: string; color: 'success' | 'warning' | 'muted' }> = {
    all: { label: 'All', color: 'muted' },
    [FeedbackStatus.Visible]: { label: 'Visible', color: 'success' },
    [FeedbackStatus.Hidden]: { label: 'Hidden', color: 'warning' },
}

export const FeedbackFilters = (): JSX.Element => {
    const statusOptions: StatusOption[] = ['all', FeedbackStatus.Visible, FeedbackStatus.Hidden]

    const typeOptions = [
        { value: 'all', label: 'All types' },
        { value: 'bug', label: 'Bug' },
        { value: 'feature_request', label: 'Feature request' },
        { value: 'improvement', label: 'Improvement' },
        { value: 'other', label: 'Other' },
    ]

    return (
        <div className="bg-bg-light border rounded p-4">
            <div className="flex gap-2">
                <LemonInput fullWidth type="search" placeholder="it doesn't do anything (yet)" />
                <LemonSelect
                    value="all"
                    placeholder="Select status"
                    options={statusOptions.map((status) => ({
                        value: status,
                        label: (
                            <div className="flex items-center gap-2 text-sm">
                                <LemonBadge status={STATUS_LABELS[status].color} size="small" />
                                <span>{STATUS_LABELS[status].label}</span>
                            </div>
                        ),
                    }))}
                    size="small"
                />
                <LemonSelect value="all" placeholder="Select type" options={typeOptions} size="small" />
            </div>
        </div>
    )
}
