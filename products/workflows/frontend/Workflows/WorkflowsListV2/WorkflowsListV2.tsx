import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { serializeFacetQuery } from 'lib/components/FacetSearchBar/facetQuery'
import { FacetSearchBar } from 'lib/components/FacetSearchBar/FacetSearchBar'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonTable } from 'lib/lemon-ui/LemonTable'

import { workflowLogic } from '../workflowLogic'
import { buildWorkflowsListV2Columns } from './workflowsListV2Columns'
import { workflowsListV2Logic } from './workflowsListV2Logic'

const PAGE_SIZE = 100

export function WorkflowsListV2(): JSX.Element {
    const { rows, filteredRows, facets, matchesText, value, listLoaded, listDataLoading, loadFailed, shownColumns } =
        useValues(workflowsListV2Logic)
    const { setValue, loadList, clearFilters } = useActions(workflowsListV2Logic)

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
                        loading={listDataLoading}
                        onClick={loadList}
                        data-attr="workflows-list-v2-retry"
                    >
                        Retry
                    </LemonButton>
                </div>
            )
        }
        if (listLoaded && rows.length > 0 && filteredRows.length === 0) {
            return (
                <div className="flex flex-col items-center gap-2 border rounded p-8 text-center">
                    <span>No workflows or email templates match these filters</span>
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
                loading={!listLoaded}
                rowKey={(row) => `${row.kind}-${row.id}`}
                columns={buildWorkflowsListV2Columns(shownColumns, value.filters)}
                // Client-side pages stay out of the URL; `page` there is an old list param.
                pagination={{ pageSize: PAGE_SIZE, useUrl: false }}
                nouns={['item', 'items']}
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
                placeholder="Search workflows, or filter with status:, channel:, from: and more"
                dataAttr="workflows-search"
            />
            {renderBody()}
        </div>
    )
}
