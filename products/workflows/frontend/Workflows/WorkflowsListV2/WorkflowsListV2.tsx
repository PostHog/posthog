import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonTable } from 'lib/lemon-ui/LemonTable'

import { AutomationEmptyState } from '../../setupGuide/AutomationEmptyState'
import { AutomationSuggestionBanner } from '../../setupGuide/AutomationSuggestionBanner'
import { MessagingSetupReminderBanner } from '../../setupGuide/MessagingSetupReminderBanner'
import { workflowLogic } from '../workflowLogic'
import { serializeFacetQuery } from './FacetSearchBar/facetQuery'
import { FacetSearchBar } from './FacetSearchBar/FacetSearchBar'
import { buildWorkflowsListV2Columns } from './workflowsListV2Columns'
import { workflowsListV2Logic } from './workflowsListV2Logic'

const PAGE_SIZE = 100

export function WorkflowsListV2(): JSX.Element {
    const {
        rows,
        filteredRows,
        facets,
        matchesText,
        value,
        listLoaded,
        listComplete,
        loadingMoreWorkflows,
        workflowsLoading,
        loadFailed,
        loadErrorDetail,
        shownColumns,
        metricsLoading,
        serverSearchStatus,
        isUnfilteredAutomationView,
        hasHealthFilter,
        metricsLoaded,
        metricsStatus,
    } = useValues(workflowsListV2Logic)
    const { setValue, loadWorkflows, loadMetrics, clearFilters } = useActions(workflowsListV2Logic)
    // A new filter starts again on page one, as the flag-off list does.
    const filterKey = `${serializeFacetQuery(value.filters)}\n${value.text}`
    const [pageForFilter, setPageForFilter] = useState({ filterKey, page: 1 })
    const currentPage = pageForFilter.filterKey === filterKey ? pageForFilter.page : 1

    useOnMountEffect(() => {
        // Leaving the new-workflow scene keeps its logic mounted, so drop it here as WorkflowsTable does.
        workflowLogic.findMounted({ id: 'new' })?.unmount()
    })

    const renderLoadError = (title: string): JSX.Element => (
        <div className="flex flex-col items-center gap-2 border rounded p-8 text-center">
            <span className="font-semibold">{title}</span>
            {loadErrorDetail && <span className="text-secondary">{loadErrorDetail}</span>}
            <LemonButton
                type="secondary"
                size="small"
                loading={workflowsLoading}
                onClick={loadWorkflows}
                data-attr="workflows-list-v2-retry"
            >
                Retry
            </LemonButton>
        </div>
    )

    const renderBody = (): JSX.Element => {
        if (loadFailed && !listLoaded) {
            return renderLoadError("Couldn't load workflows")
        }
        const searchPending = serverSearchStatus === 'pending'
        const healthPending = hasHealthFilter && !metricsLoaded
        if (hasHealthFilter && metricsStatus === 'failed') {
            return (
                <>
                    {loadFailed && !listComplete && renderLoadError("Couldn't load all workflows")}
                    <div className="flex flex-col items-center gap-2 border rounded p-8 text-center">
                        <span>Couldn't load run metrics for these health filters</span>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={loadMetrics}
                            data-attr="workflows-list-v2-metrics-retry"
                        >
                            Retry
                        </LemonButton>
                    </div>
                </>
            )
        }
        // Rows on pages still to come, or on a page that failed, could match, so nothing is empty yet.
        if (listComplete && filteredRows.length === 0 && isUnfilteredAutomationView && !searchPending) {
            return <AutomationEmptyState />
        }
        if (listComplete && rows.length > 0 && filteredRows.length === 0 && !searchPending && !healthPending) {
            return (
                <div className="flex flex-col items-center gap-2 border rounded p-8 text-center">
                    <span>No workflows match these filters</span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={clearFilters}
                        data-attr="workflows-list-v2-clear-filters"
                    >
                        Clear filters
                    </LemonButton>
                </div>
            )
        }
        return (
            <>
                {loadFailed && !listComplete && renderLoadError("Couldn't load all workflows")}
                <LemonTable
                    size="small"
                    dataSource={filteredRows}
                    // Until the server search answers, a match in an email body can still add rows.
                    loading={
                        !listLoaded ||
                        searchPending ||
                        healthPending ||
                        (loadingMoreWorkflows && filteredRows.length === 0)
                    }
                    rowKey="id"
                    columns={buildWorkflowsListV2Columns(shownColumns, metricsLoading)}
                    // Client-side pages stay out of the URL; `page` there is an old list param.
                    pagination={{
                        pageSize: PAGE_SIZE,
                        currentPage,
                        onPageChange: (page) => setPageForFilter({ filterKey, page }),
                    }}
                    nouns={['workflow', 'workflows']}
                    emptyState={listComplete ? 'No workflows yet' : 'None of the workflows loaded so far match'}
                />
                {loadingMoreWorkflows && <div className="text-xs text-secondary">Loading more workflows…</div>}
            </>
        )
    }

    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="workflows-list-v2">
            <MessagingSetupReminderBanner />
            <FacetSearchBar
                facets={facets}
                items={rows}
                value={value}
                onChange={setValue}
                matchesText={matchesText}
                placeholder="Search workflows, or filter with status:, owner:, health: and more"
                dataAttr="workflows-search"
            />
            {serverSearchStatus === 'failed' && (
                <div className="text-xs text-secondary" data-attr="workflows-list-v2-search-failed">
                    Couldn't search step names and email content. Showing matches on name and description only.
                </div>
            )}
            {renderBody()}
            <AutomationSuggestionBanner />
        </div>
    )
}
