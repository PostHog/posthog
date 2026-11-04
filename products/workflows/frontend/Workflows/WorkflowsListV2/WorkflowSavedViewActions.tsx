import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { SavedViewAction, WorkflowSavedView } from './workflowSavedViews'

export interface WorkflowSavedViewActionsProps {
    activeView: WorkflowSavedView
    isModified: boolean
    hasAddedFilters: boolean
    activeViewConflicted: boolean
    canUpdateActiveView: boolean
    activeViewChanges: string[]
    pendingAction: SavedViewAction | null
    writeDisabledReason?: string
    sharedSaveDisabledReason?: string
    onReset: () => void
    onSaveAs: () => void
    onSave: () => void
    onRename: () => void
    onDelete: () => void
}

const PENDING_ACTION_REASONS: Record<SavedViewAction, string> = {
    'save-as': 'Saving the new view',
    update: 'Updating the view',
    rename: 'Renaming the view',
    delete: 'Deleting the view',
    restore: 'Restoring My workflows',
    reset: 'Loading the latest version of the view',
}

export function WorkflowSavedViewActions({
    activeView,
    isModified,
    hasAddedFilters,
    activeViewConflicted,
    canUpdateActiveView,
    activeViewChanges,
    pendingAction,
    writeDisabledReason,
    sharedSaveDisabledReason,
    onReset,
    onSaveAs,
    onSave,
    onRename,
    onDelete,
}: WorkflowSavedViewActionsProps): JSX.Element {
    const changed = activeViewChanges.join(', ')
    const startedBy = (...actions: SavedViewAction[]): boolean =>
        pendingAction !== null && actions.includes(pendingAction)
    const pendingReason = pendingAction ? PENDING_ACTION_REASONS[pendingAction] : undefined
    return (
        <div className="flex flex-wrap items-center gap-1 pb-2 shrink-0" data-attr="workflows-combined-view-actions">
            {(isModified || hasAddedFilters || activeViewConflicted) && (
                <LemonButton
                    size="small"
                    type="tertiary"
                    onClick={onReset}
                    loading={startedBy('reset')}
                    disabledReason={pendingReason}
                    tooltip={
                        isModified || hasAddedFilters
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
