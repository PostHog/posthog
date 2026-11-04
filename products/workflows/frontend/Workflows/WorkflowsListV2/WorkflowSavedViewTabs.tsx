import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { openDeleteWorkflowSavedViewDialog, openWorkflowSavedViewDialog } from './openWorkflowSavedViewDialog'
import { WorkflowSavedViewActions } from './WorkflowSavedViewActions'
import { WorkflowSavedViewTabsRow } from './WorkflowSavedViewTabsRow'
import { workflowsSavedViewsLogic } from './workflowsSavedViewsLogic'

async function keepDialogOpenOnFailure(mutation: Promise<void>): Promise<void> {
    await mutation
    const failure = workflowsSavedViewsLogic.values.mutationFailure
    if (failure) {
        throw failure
    }
}

export function WorkflowSavedViewTabs(): JSX.Element | null {
    const {
        available,
        views,
        activeViewId,
        viewCounts,
        isModified,
        activeViewChanges,
        activeView,
        canUpdateActiveView,
        activeViewConflicted,
        pendingAction,
        sharedSaveDisabledReason,
        writeDisabledReason,
        savedViewsLoadFailed,
        savedViewsLoading,
        addedFilters,
    } = useValues(workflowsSavedViewsLogic)
    const { applyView, resetView, updateActiveView, loadSavedViews } = useActions(workflowsSavedViewsLogic)
    if (savedViewsLoadFailed) {
        return (
            <LemonBanner type="warning" className="mb-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>Couldn't load saved views. Saved filters haven't been applied.</span>
                    <LemonButton type="secondary" size="small" loading={savedViewsLoading} onClick={loadSavedViews}>
                        Retry
                    </LemonButton>
                </div>
            </LemonBanner>
        )
    }
    if (!available) {
        return null
    }
    const saveRoom = isModified ? 2 : addedFilters.length || activeViewConflicted ? 1 : 0
    const rowProps = { views, activeViewId, viewCounts, isModified, activeViewChanges, onApplyView: applyView }
    return (
        <div className="@container/saved-views">
            <div className="flex flex-col @min-[42rem]/saved-views:flex-row @min-[42rem]/saved-views:items-end gap-2">
                <div className="flex-1 min-w-0">
                    <div className="@4xl:hidden">
                        <WorkflowSavedViewTabsRow {...rowProps} max={3} />
                    </div>
                    <div className="hidden @4xl:block @6xl:hidden">
                        <WorkflowSavedViewTabsRow {...rowProps} max={5 - Math.min(saveRoom, 1)} />
                    </div>
                    <div className="hidden @6xl:block">
                        <WorkflowSavedViewTabsRow {...rowProps} max={7 - saveRoom} />
                    </div>
                </div>
                <WorkflowSavedViewActions
                    activeView={activeView}
                    isModified={isModified}
                    hasAddedFilters={addedFilters.length > 0}
                    activeViewConflicted={activeViewConflicted}
                    canUpdateActiveView={canUpdateActiveView}
                    activeViewChanges={activeViewChanges}
                    pendingAction={pendingAction}
                    sharedSaveDisabledReason={sharedSaveDisabledReason}
                    writeDisabledReason={writeDisabledReason}
                    onReset={() => resetView()}
                    onSaveAs={() =>
                        openWorkflowSavedViewDialog((name) =>
                            keepDialogOpenOnFailure(workflowsSavedViewsLogic.asyncActions.saveViewAs(name))
                        )
                    }
                    onSave={updateActiveView}
                    onRename={() =>
                        openWorkflowSavedViewDialog(
                            (name) =>
                                keepDialogOpenOnFailure(
                                    workflowsSavedViewsLogic.asyncActions.renameView(activeView.id, name)
                                ),
                            activeView.name
                        )
                    }
                    onDelete={() =>
                        openDeleteWorkflowSavedViewDialog(
                            activeView.name,
                            async () => await workflowsSavedViewsLogic.asyncActions.deleteView(activeView.id)
                        )
                    }
                />
            </div>
        </div>
    )
}
