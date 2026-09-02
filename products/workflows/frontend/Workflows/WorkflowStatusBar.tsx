import { useValues, useActions } from 'kea'

import { IconClock, IconInfo } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LastSavedIndicator } from 'lib/components/LastSavedIndicator'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { urls } from 'scenes/urls'

import { WorkflowLogicProps, workflowLogic } from './workflowLogic'

/**
 * State narration for a saved workflow: what you're editing (live config vs staged draft), save
 * state, and the auto-save toggle. Deliberately no write actions here - save/publish/discard live
 * in the scene header with every other scene's primary actions, and in the scene menu bar.
 */
export function WorkflowStatusBar(props: WorkflowLogicProps): JSX.Element | null {
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

    if (!props.id || props.id === 'new' || props.editTemplateId || !originalWorkflow) {
        return null
    }

    const isActive = originalWorkflow.status === 'active'
    const isEditingDraftOfLive = isActive && (hasStagedDraft || hasUnsavedChanges)

    return (
        <div className="flex items-center justify-between gap-2 px-2 py-1.5 border-b bg-surface-secondary rounded-t-md flex-wrap">
            <div className="flex items-center gap-3 min-w-0">
                {isEditingDraftOfLive ? (
                    <LemonTag type="warning">Editing draft</LemonTag>
                ) : isActive ? (
                    <LemonTag type="success">Live</LemonTag>
                ) : (
                    <LemonTag>Draft</LemonTag>
                )}
                {isActive && (
                    <span className="text-xs text-secondary truncate">
                        {isEditingDraftOfLive
                            ? 'The live version keeps running until you publish.'
                            : 'Changes you make save as a draft.'}
                    </span>
                )}
            </div>
            {/* Interactive controls sit right-anchored with variable-width text leftmost, so the
                toggle and History never shift as the narration or the timestamp changes. */}
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
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconClock />}
                    to={urls.workflow(props.id, 'history')}
                    tooltip="See and restore previous versions"
                >
                    History
                </LemonButton>
            </div>
        </div>
    )
}
