import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconBug, IconQuestion } from '@posthog/icons'
import { LemonBadge, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { IconFeedback } from '~/lib/lemon-ui/icons'

import { filtersLogic } from '../../logics/filtersLogic'
import { FeedbackStatus, FeedbackType, StatusOption, TypeOption } from '../../types'

const STATUS_LABELS: Record<StatusOption, { label: string; color: 'success' | 'warning' | 'muted' }> = {
    all: { label: 'All', color: 'muted' },
    [FeedbackStatus.Visible]: { label: 'Visible', color: 'success' },
    [FeedbackStatus.Hidden]: { label: 'Hidden', color: 'warning' },
}

const TYPE_LABELS: Record<TypeOption, { label: string; icon: JSX.Element }> = {
    all: { label: 'All types', icon: <></> },
    [FeedbackType.Question]: { label: 'Question', icon: <IconQuestion /> },
    [FeedbackType.Feedback]: { label: 'Feedback', icon: <IconFeedback /> },
    [FeedbackType.Bug]: { label: 'Bug', icon: <IconBug /> },
}

export const FeedbackFilters = (): JSX.Element => {
    const statusOptions: StatusOption[] = ['all', FeedbackStatus.Visible, FeedbackStatus.Hidden]
    const typeOptions: TypeOption[] = ['all', FeedbackType.Question, FeedbackType.Feedback, FeedbackType.Bug]

    const { statusFilter, typeFilter } = useValues(filtersLogic)
    const { setStatusFilter, setTypeFilter } = useActions(filtersLogic)

    const statusOption = useMemo(() => {
        if (!statusFilter) {
            return 'all'
        } else {
            return statusFilter
        }
    }, [statusFilter])

    const typeOption = useMemo(() => {
        if (!typeFilter) {
            return 'all'
        } else {
            return typeFilter
        }
    }, [typeFilter])

    return (
        <div className="bg-bg-light border rounded p-4">
            <div className="flex gap-2">
                <LemonInput fullWidth type="search" placeholder="it doesn't do anything (yet)" />
                <LemonSelect
                    value={statusOption}
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
                    onChange={(status) => {
                        if (status === 'all') {
                            setStatusFilter(null)
                        } else {
                            setStatusFilter(status)
                        }
                    }}
                />
                <LemonSelect
                    value={typeOption}
                    placeholder="Select type"
                    options={typeOptions.map((type) => ({
                        value: type,
                        label: (
                            <div className="flex items-center gap-2 text-sm">
                                {TYPE_LABELS[type].icon}
                                <span>{TYPE_LABELS[type].label}</span>
                            </div>
                        ),
                    }))}
                    size="small"
                    onChange={(type) => {
                        if (type === 'all') {
                            setTypeFilter(null)
                        } else {
                            setTypeFilter(type)
                        }
                    }}
                />
            </div>
        </div>
    )
}
