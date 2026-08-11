import { useValues, useActions } from 'kea'

import { IconClock, IconInfo } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LastSavedIndicator } from 'lib/components/LastSavedIndicator'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { WorkflowLogicProps, workflowLogic } from './workflowLogic'

/**
 * The single home for the content lifecycle of a saved workflow: what you're editing (live config
 * vs staged draft), save state, and the save/publish/discard actions. Lifecycle (enable/disable)
 * stays in the scene header.
 */
export function WorkflowStatusBar(props: WorkflowLogicProps): JSX.Element | null {
    const logic = workflowLogic(props)
    const {
        originalWorkflow,
        workflowLoading,
        hasUnsavedChanges,
        hasStagedDraft,
        draftActionPending,
        isAutoSavePending,
        autoSaveEnabled,
        lastSavedAt,
        isWorkflowSubmitting,
        workflowHasErrors,
        workflowUserAccessLevel,
    } = useValues(logic)
    const { submitWorkflow, discardChanges, publishDraft, discardDraft, setAutoSaveEnabled } = useActions(logic)
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
                {autoSaveEnabled && showSaving ? (
                    <span className="text-xs text-tertiary flex items-center gap-1 shrink-0">
                        <Spinner textColored /> Saving…
                    </span>
                ) : lastSavedAt ? (
                    <LastSavedIndicator timestamp={lastSavedAt} />
                ) : null}
                <span className="flex items-center gap-1 shrink-0">
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
            <div className="flex items-center gap-2 shrink-0">
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconClock />}
                    to={urls.workflow(props.id, 'history')}
                    tooltip="See and restore previous versions"
                >
                    History
                </LemonButton>
                {hasUnsavedChanges && (
                    <LemonButton
                        data-attr="discard-workflow-changes"
                        type="secondary"
                        size="small"
                        onClick={() => discardChanges()}
                    >
                        Clear changes
                    </LemonButton>
                )}
                <AccessControlAction
                    resourceType={AccessControlResourceType.Workflow}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={workflowUserAccessLevel ?? undefined}
                >
                    <LemonButton
                        data-attr="workflow-save"
                        type={isEditingDraftOfLive ? 'secondary' : 'primary'}
                        size="small"
                        htmlType="submit"
                        form="workflow"
                        onClick={submitWorkflow}
                        loading={isWorkflowSubmitting}
                        disabledReason={
                            workflowHasErrors
                                ? 'Some fields still need work'
                                : !hasUnsavedChanges
                                  ? 'No changes to save'
                                  : undefined
                        }
                    >
                        {isActive ? 'Save draft' : 'Save'}
                    </LemonButton>
                </AccessControlAction>
                {hasStagedDraft && (
                    <>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Workflow}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={workflowUserAccessLevel ?? undefined}
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                status="danger"
                                onClick={() => discardDraft()}
                                loading={draftActionPending === 'discard'}
                                disabledReason={
                                    hasUnsavedChanges
                                        ? 'Save or clear your in-progress edits first'
                                        : draftActionPending === 'publish'
                                          ? 'Publishing is in progress'
                                          : undefined
                                }
                            >
                                Discard draft
                            </LemonButton>
                        </AccessControlAction>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Workflow}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={workflowUserAccessLevel ?? undefined}
                        >
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={() => publishDraft()}
                                loading={draftActionPending === 'publish'}
                                disabledReason={
                                    hasUnsavedChanges
                                        ? 'Save or clear your in-progress edits first'
                                        : draftActionPending === 'discard'
                                          ? 'Discarding is in progress'
                                          : undefined
                                }
                            >
                                Publish
                            </LemonButton>
                        </AccessControlAction>
                    </>
                )}
            </div>
        </div>
    )
}
