import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { InboxDemoSort } from '../types'
import { GROUP_PAGE_SIZE, InboxReportGroup, PRODUCT_OPTIONS, v2InboxLogic } from '../v2InboxLogic'
import { GroupedReportRow } from './GroupedReportRow'
import { InboxViewControls } from './InboxViewControls'

const SORT_OPTIONS: { value: InboxDemoSort; label: string }[] = [
    { value: 'users', label: 'Number of users' },
    { value: 'recency', label: 'Recency' },
]

function ReportGroupSection({ group }: { group: InboxReportGroup }): JSX.Element {
    const { openGroups, visibleGroupCounts } = useValues(v2InboxLogic)
    const { showMoreInGroup, toggleGroupOpen } = useActions(v2InboxLogic)

    const isOpen = openGroups[group.key]
    const visibleCount = visibleGroupCounts[group.key] ?? GROUP_PAGE_SIZE
    const visibleReports = group.reports.slice(0, visibleCount)
    const hiddenCount = group.reports.length - visibleReports.length

    return (
        <section className="flex flex-col gap-2">
            <button
                type="button"
                className="flex w-full items-center gap-3 rounded px-0.5 text-left"
                onClick={() => toggleGroupOpen(group.key)}
                aria-expanded={isOpen}
                data-attr={`v2-group-toggle-${group.key}`}
            >
                <span className="font-mono text-[11px] font-semibold tracking-widest uppercase text-secondary">
                    {group.label} ({group.reports.length})
                </span>
                <div className="h-px flex-1 bg-border-primary" />
                <IconChevronDown className={cn('text-tertiary', isOpen && 'rotate-180')} />
            </button>
            {isOpen && (
                <div className="flex flex-col gap-1.5">
                    {group.reports.length === 0 ? (
                        <span className="px-4 py-2 text-sm text-tertiary">Nothing here right now.</span>
                    ) : (
                        visibleReports.map((report) => (
                            <GroupedReportRow key={report.id} report={report} group={group.key} />
                        ))
                    )}
                    {hiddenCount > 0 && (
                        <div className="flex justify-center">
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={() => showMoreInGroup(group.key)}
                                data-attr={`v2-group-show-more-${group.key}`}
                            >
                                Show more ({hiddenCount})
                            </LemonButton>
                        </div>
                    )}
                </div>
            )}
        </section>
    )
}

export function InboxGroupedReportsTab(): JSX.Element {
    const { productFilter, sort, groupedReports } = useValues(v2InboxLogic)
    const { setProductFilter, setSort } = useActions(v2InboxLogic)

    const total = groupedReports.reduce((sum, group) => sum + group.reports.length, 0)

    return (
        <div className="flex flex-col gap-5">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <LemonSelect
                    size="small"
                    value={productFilter}
                    onChange={setProductFilter}
                    options={PRODUCT_OPTIONS}
                    data-attr="v2-filter-product"
                />
                <LemonSelect
                    size="small"
                    value={sort}
                    onChange={setSort}
                    options={SORT_OPTIONS}
                    renderButtonContent={(leaf) => `Sort: ${leaf?.label ?? ''}`}
                    data-attr="v2-sort"
                />
                <div className="flex-1" />
                <InboxViewControls />
            </div>

            {total === 0 ? (
                <div className="rounded border border-primary bg-surface-primary px-4 py-6 text-center text-sm text-secondary">
                    No reports match these filters. Pick another product, or switch to Entire project.
                </div>
            ) : (
                groupedReports.map((group) => <ReportGroupSection key={group.key} group={group} />)
            )}
        </div>
    )
}
