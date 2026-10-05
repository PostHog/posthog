import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonTable } from 'lib/lemon-ui/LemonTable'

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
        workflowsLoading,
        loadFailed,
        shownColumns,
        metricsLoading,
        serverSearchStatus,
    } = useValues(workflowsListV2Logic)
    const { setValue, loadWorkflows, clearFilters } = useActions(workflowsListV2Logic)

    useOnMountEffect(() => {
        // Leaving the new-workflow scene keeps its logic mounted, so drop it here as WorkflowsTable does.
        workflowLogic.findMounted({ id: 'new' })?.unmount()
    })

    const renderBody = (): JSX.Element => {
        if (loadFailed) {
            return (
                <div className="flex flex-col items-center gap-2 border rounded p-8 text-center">
                    <span className="font-semibold">Couldn't load workflows</span>
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
        }
        const searchPending = serverSearchStatus === 'pending'
        if (listLoaded && rows.length > 0 && filteredRows.length === 0 && !searchPending) {
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
            <LemonTable
                // A new filter starts again on page one, as the flag-off list does.
                key={`${serializeFacetQuery(value.filters)}\n${value.text}`}
                size="small"
                dataSource={filteredRows}
                // Until the server search answers, a match in an email body can still add rows.
                loading={!listLoaded || searchPending}
                rowKey="id"
                columns={buildWorkflowsListV2Columns(shownColumns, metricsLoading)}
                // Client-side pages stay out of the URL; `page` there is an old list param.
                pagination={{ pageSize: PAGE_SIZE, useUrl: false }}
                nouns={['workflow', 'workflows']}
                emptyState="No workflows yet"
            />
        )
    }

    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="workflows-list-v2">
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
        </div>
    )
}
