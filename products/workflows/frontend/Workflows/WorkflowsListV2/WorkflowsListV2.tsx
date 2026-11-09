import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonTable } from 'lib/lemon-ui/LemonTable'

import { AutomationEmptyState } from '../../setupGuide/AutomationEmptyState'
import { AutomationSuggestionBanner } from '../../setupGuide/AutomationSuggestionBanner'
import { MessagingSetupReminderBanner } from '../../setupGuide/MessagingSetupReminderBanner'
import { workflowLogic } from '../workflowLogic'
import { serializeFacetQuery } from './FacetSearchBar/facetQuery'
import { FacetSearchBar } from './FacetSearchBar/FacetSearchBar'
import { WorkflowFolderContents } from './WorkflowFolderContents'
import { WorkflowFolderDropMonitor } from './WorkflowFolderDropMonitor'
import { WorkflowFolderSidebar } from './WorkflowFolderSidebar'
import { workflowFoldersLogic } from './workflowFoldersLogic'
import { WorkflowFolderToolbar } from './WorkflowFolderToolbar'
import { WorkflowSavedViewTabs } from './WorkflowSavedViewTabs'
import { buildWorkflowsListV2Columns } from './workflowsListV2Columns'
import { workflowsListV2Logic } from './workflowsListV2Logic'
import { workflowsSavedViewsLogic } from './workflowsSavedViewsLogic'

const PAGE_SIZE = 100

export function WorkflowsListV2(): JSX.Element {
    const { viewFilters, viewsResolving } = useValues(workflowsSavedViewsLogic)
    const {
        projectFilesEnabled,
        rows,
        filteredRows,
        facets,
        matchesText,
        value,
        listLoaded,
        workflowsLoading,
        loadFailed,
        loadErrorDetail,
        shownColumns,
        metricsLoading,
        serverSearchStatus,
        isUnfilteredAutomationView,
        hasHealthFilter,
        metricsLoaded,
    } = useValues(workflowsListV2Logic)
    const { setValue, loadWorkflows, loadMetrics, clearFilters } = useActions(workflowsListV2Logic)
    const {
        currentFolder,
        browserLoadFailed,
        browserReadyLoading,
        folderFacets,
        folderSearchItems,
        folderMatchesText,
        displayedValue,
    } = useValues(workflowFoldersLogic)

    useOnMountEffect(() => {
        // Leaving the new-workflow scene keeps its logic mounted, so drop it here as WorkflowsTable does.
        workflowLogic.findMounted({ id: 'new' })?.unmount()
    })

    const { loadBrowser } = useActions(workflowFoldersLogic)
    // The folder view shows the same metrics retry as the flat list when health pills cannot be checked.
    const metricsFailed = listLoaded && hasHealthFilter && !metricsLoaded && !metricsLoading
    const renderBody = (): JSX.Element => {
        if (browserLoadFailed) {
            return (
                <div className="border rounded p-8 text-center">
                    <span>Couldn't load project folders</span>
                    <LemonButton onClick={() => loadBrowser()} loading={browserReadyLoading}>
                        Retry
                    </LemonButton>
                </div>
            )
        }
        if (loadFailed && !listLoaded) {
            return (
                <div className="flex flex-col items-center gap-2 border rounded p-8 text-center">
                    <span className="font-semibold">Couldn't load workflows</span>
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
        }
        if (viewsResolving) {
            return (
                <LemonTable
                    size="small"
                    dataSource={[]}
                    loading
                    columns={buildWorkflowsListV2Columns(shownColumns, metricsLoading)}
                    nouns={['workflow', 'workflows']}
                    data-attr="workflows-list-v2-views-loading"
                />
            )
        }
        const searchPending = serverSearchStatus === 'pending'
        const healthPending = hasHealthFilter && !metricsLoaded
        if (listLoaded && healthPending && !metricsLoading) {
            return (
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
            )
        }
        if (listLoaded && filteredRows.length === 0 && isUnfilteredAutomationView && !searchPending) {
            return <AutomationEmptyState />
        }
        if (listLoaded && rows.length > 0 && filteredRows.length === 0 && !searchPending && !healthPending) {
            return (
                <div className="flex flex-col items-center gap-2 border rounded p-8 text-center">
                    <span>
                        {currentFolder === null
                            ? 'No workflows match these filters'
                            : 'No workflows in this folder match these filters'}
                    </span>
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
                loading={!listLoaded || searchPending || healthPending}
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
            <MessagingSetupReminderBanner />
            <div>
                <WorkflowSavedViewTabs />
                {projectFilesEnabled ? (
                    <FacetSearchBar
                        facets={folderFacets}
                        items={folderSearchItems}
                        value={displayedValue}
                        viewFilters={viewFilters}
                        onChange={setValue}
                        matchesText={folderMatchesText}
                        placeholder="Search workflows and email templates, or filter with in:, status:, kind: and more"
                        dataAttr="workflows-search"
                    />
                ) : (
                    <FacetSearchBar
                        facets={facets}
                        items={rows}
                        value={value}
                        viewFilters={viewFilters}
                        onChange={setValue}
                        matchesText={matchesText}
                        placeholder="Search workflows, or filter with status:, owner:, health: and more"
                        dataAttr="workflows-search"
                    />
                )}
            </div>
            {serverSearchStatus === 'failed' && (
                <div className="text-xs text-secondary" data-attr="workflows-list-v2-search-failed">
                    Couldn't search step names and email content. Showing matches on name and description only.
                </div>
            )}
            {projectFilesEnabled ? (
                <div className="flex flex-col gap-3 @min-[48rem]/main-content:flex-row min-w-0 min-h-[calc(100vh-20rem)]">
                    <WorkflowFolderSidebar />
                    <div className="min-w-0 flex-1 @container">
                        <WorkflowFolderDropMonitor />
                        <WorkflowFolderToolbar />
                        {(loadFailed && !listLoaded) || browserLoadFailed || metricsFailed || viewsResolving ? (
                            renderBody()
                        ) : (
                            <WorkflowFolderContents />
                        )}
                    </div>
                </div>
            ) : (
                renderBody()
            )}
            <AutomationSuggestionBanner />
        </div>
    )
}
