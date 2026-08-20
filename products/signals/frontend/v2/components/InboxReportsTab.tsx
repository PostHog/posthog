import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { InboxDemoFilter } from '../types'
import { PRODUCT_OPTIONS, v2InboxLogic } from '../v2InboxLogic'
import { InboxViewControls } from './InboxViewControls'
import { ReportRow } from './ReportRow'

const FILTER_OPTIONS: { value: InboxDemoFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'open', label: 'Open' },
    { value: 'monitoring', label: 'Monitoring' },
    { value: 'archived', label: 'Archived' },
]

export function InboxReportsTab(): JSX.Element {
    const { filter, productFilter, filteredReports } = useValues(v2InboxLogic)
    const { setFilter, setProductFilter } = useActions(v2InboxLogic)

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
                <LemonSelect
                    size="small"
                    value={productFilter}
                    onChange={setProductFilter}
                    options={PRODUCT_OPTIONS}
                    data-attr="v2-filter-product"
                />
                <div className="flex-1" />
                <InboxViewControls />
            </div>

            <div className="flex flex-col gap-2">
                {filteredReports.length === 0 ? (
                    <div className="rounded border border-primary bg-surface-primary px-4 py-6 text-center text-sm text-secondary">
                        No reports match these filters. Pick another status or product, or switch to Entire project.
                    </div>
                ) : (
                    filteredReports.map((report) => <ReportRow key={report.id} report={report} />)
                )}
            </div>
        </div>
    )
}
