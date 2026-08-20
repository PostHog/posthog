import { useActions, useValues } from 'kea'

import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { urls } from 'scenes/urls'

import { InboxDemoFilter, InboxDemoSort } from '../types'
import { v2InboxLogic } from '../v2InboxLogic'
import { ReportRow } from './ReportRow'

const FILTER_OPTIONS: { value: InboxDemoFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'open', label: 'Open' },
    { value: 'monitoring', label: 'Monitoring' },
    { value: 'archived', label: 'Archived' },
]

const SORT_OPTIONS: { value: InboxDemoSort; label: string }[] = [
    { value: 'impact', label: 'Impact' },
    { value: 'recency', label: 'Recency' },
]

export function InboxReportsTab(): JSX.Element {
    const { filter, sort, filteredReports } = useValues(v2InboxLogic)
    const { setFilter, setSort } = useActions(v2InboxLogic)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <div className="flex flex-wrap items-center gap-1">
                    {FILTER_OPTIONS.map((option) => (
                        <LemonButton
                            key={option.value}
                            size="small"
                            type="secondary"
                            active={filter === option.value}
                            onClick={() => setFilter(option.value)}
                            data-attr={`v2-filter-${option.value}`}
                        >
                            {option.label}
                        </LemonButton>
                    ))}
                </div>
                <div className="flex-1" />
                <LemonButton
                    type="primary"
                    size="small"
                    to={urls.v2Focus()}
                    sideIcon={<KeyboardShortcut f />}
                    data-attr="v2-focus-mode"
                >
                    Focus mode
                </LemonButton>
                <span className="text-xs text-tertiary">Sort by</span>
                <LemonSegmentedButton
                    size="small"
                    value={sort}
                    onChange={setSort}
                    options={SORT_OPTIONS.map((option) => ({
                        ...option,
                        'data-attr': `v2-sort-${option.value}`,
                    }))}
                />
            </div>

            <div className="flex flex-col gap-2">
                {filteredReports.length === 0 ? (
                    <div className="rounded border border-primary bg-surface-primary px-4 py-6 text-center text-sm text-secondary">
                        No reports match this filter. Pick another filter to see more.
                    </div>
                ) : (
                    filteredReports.map((report) => <ReportRow key={report.id} report={report} />)
                )}
            </div>
        </div>
    )
}
