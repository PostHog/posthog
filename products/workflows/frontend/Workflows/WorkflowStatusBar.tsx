import { useValues, useActions } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonSwitch, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LastSavedIndicator } from 'lib/components/LastSavedIndicator'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'

import { WorkflowLogicProps, workflowLogic } from './workflowLogic'

type WorkflowStatusBarProps = WorkflowLogicProps & {
    commands: JSX.Element
}

export function WorkflowStatusBar({ commands, ...props }: WorkflowStatusBarProps): JSX.Element | null {
    const logic = workflowLogic(props)
    const {
        originalWorkflow,
        workflowLoading,
        hasUnsavedChanges,
        hasStagedDraft,
        isAutoSavePending,
        autoSaveEnabled,
        lastSavedAt,
    } = useValues(logic)
    const { setAutoSaveEnabled } = useActions(logic)
    const showSaving = useDebouncedValue(isAutoSavePending || workflowLoading, 1000)

    if (!originalWorkflow) {
        return null
    }

    const showWorkflowStatus = !props.editTemplateId
    const historyWorkflowId = props.id && props.id !== 'new' ? props.id : null
    const isActive = originalWorkflow.status === 'active'
    const isEditingDraftOfLive = isActive && (hasStagedDraft || hasUnsavedChanges)

    return (
        <div className="@container/workflow-status flex items-center justify-between gap-2 px-2 py-1.5 border-b bg-surface-secondary rounded-t-md flex-wrap">
            <div className="flex items-center gap-3 min-w-0">
                {showWorkflowStatus &&
                    (isEditingDraftOfLive ? (
                        <LemonTag type="warning">Editing draft</LemonTag>
                    ) : isActive ? (
                        <LemonTag type="success">Live</LemonTag>
                    ) : (
                        <LemonTag>Draft</LemonTag>
                    ))}
                {showWorkflowStatus && isActive && (
                    <span className="text-xs text-secondary truncate">
                        {isEditingDraftOfLive
                            ? 'The live version keeps running until you publish.'
                            : 'Changes you make save as a draft.'}
                    </span>
                )}
                {commands}
            </div>
            {/* Interactive controls sit right-anchored with variable-width text leftmost, so the
                toggle never shifts as the narration or the timestamp changes. */}
            {showWorkflowStatus && historyWorkflowId && (
                <div className="flex items-center gap-3 shrink-0">
                    {autoSaveEnabled && showSaving ? (
                        <span className="text-xs text-tertiary flex items-center gap-1">
                            <Spinner textColored /> Saving…
                        </span>
                    ) : lastSavedAt ? (
                        <LastSavedIndicator timestamp={lastSavedAt} />
                    ) : null}
                    <span className="flex items-center gap-1">
                        <LemonSwitch
                            checked={autoSaveEnabled}
                            onChange={setAutoSaveEnabled}
                            label="Auto-save"
                            size="small"
                        />
                        <Tooltip
                            title={
                                isActive
                                    ? 'Auto-save stores your changes as a draft. Nothing goes live until you publish.'
                                    : 'Draft workflows auto-save as you edit.'
                            }
                            placement="bottom"
                        >
                            <IconInfo className="text-tertiary size-4" />
                        </Tooltip>
                    </span>
                </div>
            )}
        </div>
    )
}
