import { useActions, useValues } from 'kea'

import { LemonButton, LemonTable } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { AutomationSuggestionBanner } from '../../setupGuide/AutomationSuggestionBanner'
import { MessagingSetupReminderBanner } from '../../setupGuide/MessagingSetupReminderBanner'
import { workflowLogic } from '../workflowLogic'
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

export function WorkflowsListV2(): JSX.Element {
    const { viewFilters, viewsResolving } = useValues(workflowsSavedViewsLogic)
    const {
        listLoaded,
        workflowsLoading,
        loadFailed,
        loadErrorDetail,
        metricsLoading,
        serverSearchStatus,
        hasHealthFilter,
        metricsLoaded,
        shownColumns,
    } = useValues(workflowsListV2Logic)
    const { setValue, loadWorkflows, loadMetrics } = useActions(workflowsListV2Logic)
    const {
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
    const metricsFailed = listLoaded && hasHealthFilter && !metricsLoaded && !metricsLoading
    const renderLoadError = (): JSX.Element => {
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

    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="workflows-list-v2">
            <MessagingSetupReminderBanner />
            <div>
                <WorkflowSavedViewTabs />
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
            </div>
            {serverSearchStatus === 'failed' && (
                <div className="text-xs text-secondary" data-attr="workflows-list-v2-search-failed">
                    Couldn't search step names and email content. Showing matches on name and description only.
                </div>
            )}
            <div className="flex flex-col gap-3 @min-[48rem]/main-content:flex-row min-w-0 min-h-[calc(100vh-20rem)]">
                <WorkflowFolderSidebar />
                <div className="min-w-0 flex-1 @container">
                    <WorkflowFolderDropMonitor />
                    <WorkflowFolderToolbar />
                    {(loadFailed && !listLoaded) || browserLoadFailed || metricsFailed ? (
                        renderLoadError()
                    ) : viewsResolving ? (
                        <LemonTable
                            size="small"
                            dataSource={[]}
                            loading
                            columns={buildWorkflowsListV2Columns(shownColumns, metricsLoading)}
                            nouns={['workflow', 'workflows']}
                            data-attr="workflows-list-v2-views-loading"
                        />
                    ) : (
                        <WorkflowFolderContents />
                    )}
                </div>
            </div>
            <AutomationSuggestionBanner />
        </div>
    )
}
