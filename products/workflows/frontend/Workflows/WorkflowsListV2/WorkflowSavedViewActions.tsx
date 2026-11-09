import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { openDeleteWorkflowSavedViewDialog, openWorkflowSavedViewDialog } from './openWorkflowSavedViewDialog'
import { PENDING_ACTION_REASONS, SavedViewAction } from './workflowSavedViews'
import { workflowsSavedViewsLogic } from './workflowsSavedViewsLogic'

// The dialogs stay open on a failed save, so the user can fix the name or retry.
async function keepDialogOpenOnFailure(
    mutate: (onFailure: (failure: unknown) => void) => Promise<void>
): Promise<void> {
    let failure: unknown = null
    await mutate((reported) => {
        failure = reported
    })
    if (failure) {
        throw failure
    }
}

export function WorkflowSavedViewActions(): JSX.Element {
    const {
        activeView,
        isModified,
        hasAdditions,
        activeViewConflicted,
        canUpdateActiveView,
        activeViewChanges,
        pendingAction,
        writeDisabledReason,
        sharedSaveDisabledReason,
    } = useValues(workflowsSavedViewsLogic)
    const { resetView, updateActiveView } = useActions(workflowsSavedViewsLogic)
    const onReset = (): void => resetView()
    const onSaveAs = (): void =>
        openWorkflowSavedViewDialog((name) =>
            keepDialogOpenOnFailure((onFailure) => workflowsSavedViewsLogic.asyncActions.saveViewAs(name, onFailure))
        )
    const onSave = (): void => updateActiveView()
    const onRename = (): void =>
        openWorkflowSavedViewDialog(
            (name) =>
                keepDialogOpenOnFailure((onFailure) =>
                    workflowsSavedViewsLogic.asyncActions.renameView(activeView.id, name, onFailure)
                ),
            activeView.name
        )
    const onDelete = (): void =>
        openDeleteWorkflowSavedViewDialog(
            activeView.name,
            async () => await workflowsSavedViewsLogic.asyncActions.deleteView(activeView.id)
        )
    const changed = activeViewChanges.join(', ')
    const startedBy = (...actions: SavedViewAction[]): boolean =>
        pendingAction !== null && actions.includes(pendingAction)
    const pendingReason = pendingAction ? PENDING_ACTION_REASONS[pendingAction] : undefined
    return (
        <div className="flex flex-wrap items-center gap-1 pb-2 shrink-0" data-attr="workflows-combined-view-actions">
            {(isModified || hasAdditions || activeViewConflicted) && (
                <LemonButton
                    size="small"
                    type="tertiary"
                    onClick={onReset}
                    loading={startedBy('reset')}
                    disabledReason={pendingReason}
                    tooltip={
                        isModified || hasAdditions
                            ? `Discard your changes and go back to ${activeView.name}`
                            : `Load the latest version of ${activeView.name}`
                    }
                    data-attr="workflows-combined-reset-view"
                >
                    Reset
                </LemonButton>
            )}
            {isModified && (
                <>
                    <LemonButton
                        size="small"
                        type={canUpdateActiveView ? 'secondary' : 'primary'}
                        onClick={onSaveAs}
                        loading={startedBy('save-as')}
                        disabledReason={pendingReason ?? writeDisabledReason}
                        tooltip={
                            canUpdateActiveView
                                ? `Keep ${activeView.name} as it was and save your changes as a new view`
                                : `${activeView.name} is built in and can't change. Save your changes (${changed}) as a new view.`
                        }
                        data-attr="workflows-combined-save-as-new"
                    >
                        Save as new view
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="primary"
                        onClick={onSave}
                        loading={startedBy('update')}
                        disabledReason={
                            !canUpdateActiveView
                                ? "Built-in views can't be changed. Save as a new view instead."
                                : (pendingReason ?? sharedSaveDisabledReason ?? writeDisabledReason)
                        }
                        tooltip={`Update ${activeView.name} for everyone in this project. Changed: ${changed}.`}
                        data-attr="workflows-combined-update-view"
                    >
                        Update view
                    </LemonButton>
                </>
            )}
            {canUpdateActiveView && (
                <LemonMenu
                    placement="bottom-end"
                    buttonSize="medium"
                    items={[
                        { label: 'Rename view', onClick: onRename },
                        { label: 'Delete view', status: 'danger', onClick: onDelete },
                    ]}
                >
                    <LemonButton
                        size="small"
                        type="tertiary"
                        icon={<IconEllipsis />}
                        loading={startedBy('rename', 'delete')}
                        disabledReason={pendingReason ?? writeDisabledReason}
                        data-attr="workflows-combined-view-more"
                        aria-label="More options"
                    />
                </LemonMenu>
            )}
        </div>
    )
}
