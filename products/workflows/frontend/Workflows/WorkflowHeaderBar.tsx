import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonDivider, LemonSwitch, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LastSavedIndicator } from 'lib/components/LastSavedIndicator'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SceneDescription } from '~/layout/scenes/components/SceneDescription'
import { SceneTitlePanelButton } from '~/layout/scenes/components/SceneTitlePanelButton'
import { SceneName } from '~/layout/scenes/components/SceneTitleSection'

import { WorkflowActions } from './WorkflowActions'
import { workflowBackTo } from './workflowBackTo'
import { WorkflowLogicProps, workflowLogic } from './workflowLogic'

type WorkflowHeaderBarProps = WorkflowLogicProps & {
    commands?: JSX.Element
}

const BAR_CLASS_NAME =
    'flex flex-wrap items-start justify-between gap-x-4 gap-y-2 rounded-t-md border-b bg-surface-secondary px-2 py-2'

function WorkflowHeaderBarLoading(): JSX.Element {
    return (
        <div className={BAR_CLASS_NAME}>
            <div className="flex min-w-0 flex-1 basis-72 items-start gap-1">
                <SceneBreadcrumbBackButton className="mt-0.5 shrink-0" />
                <SceneName isLoading />
            </div>
        </div>
    )
}

export function WorkflowHeaderBar({ commands, ...props }: WorkflowHeaderBarProps): JSX.Element {
    const logic = workflowLogic(props)
    const {
        originalWorkflow,
        workflow,
        workflowLoading,
        hasUnsavedChanges,
        hasStagedDraft,
        isAutoSavePending,
        autoSaveEnabled,
        lastSavedAt,
    } = useValues(logic)
    const { setAutoSaveEnabled, setWorkflowValue } = useActions(logic)
    const showSaving = useDebouncedValue(isAutoSavePending || workflowLoading, 1000)

    if (!originalWorkflow) {
        return <WorkflowHeaderBarLoading />
    }

    const showWorkflowStatus = !props.editTemplateId
    const isSaved = !!props.id && props.id !== 'new'
    // Auto-save writes to a saved workflow, so a new one shows its Create button alone.
    const showAutoSave = showWorkflowStatus && isSaved
    const isActive = originalWorkflow.status === 'active'
    const isEditingDraftOfLive = isActive && (hasStagedDraft || hasUnsavedChanges)

    return (
        <div className={BAR_CLASS_NAME}>
            <div className="flex min-w-0 flex-1 basis-72 items-start gap-1">
                <SceneBreadcrumbBackButton
                    className="mt-0.5 shrink-0"
                    forceBackTo={workflowBackTo(workflow, props.id)}
                />
                <div className="flex min-w-0 flex-1 flex-col">
                    <div className="flex min-w-0 items-center gap-2">
                        <div className="min-w-0">
                            <SceneName
                                name={workflow?.name}
                                onChange={(name) => setWorkflowValue('name', name)}
                                canEdit
                                renameDebounceMs={200}
                            />
                        </div>
                        {showWorkflowStatus &&
                            (isEditingDraftOfLive ? (
                                <Tooltip title="The live version keeps running until you publish.">
                                    <LemonTag type="warning">Editing draft</LemonTag>
                                </Tooltip>
                            ) : isActive ? (
                                <Tooltip title="Changes you make save as a draft.">
                                    <LemonTag type="success">Live</LemonTag>
                                </Tooltip>
                            ) : (
                                <LemonTag>Draft</LemonTag>
                            ))}
                    </div>
                    <SceneDescription
                        description={workflow?.description}
                        onChange={(description) => setWorkflowValue('description', description)}
                        canEdit
                        clamp
                        renameDebounceMs={200}
                    />
                </div>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-2">
                {commands}
                {commands && <LemonDivider vertical className="h-6" />}
                {showAutoSave && (
                    // A fixed width keeps the buttons beside it still while the timestamp text changes.
                    <div className="flex w-44 flex-col">
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
                        <div className="truncate leading-tight">
                            {autoSaveEnabled && showSaving ? (
                                <span className="text-xs text-tertiary inline-flex items-center gap-1">
                                    <Spinner textColored /> Saving…
                                </span>
                            ) : lastSavedAt ? (
                                <LastSavedIndicator timestamp={lastSavedAt} />
                            ) : null}
                        </div>
                    </div>
                )}
                <div className="flex flex-wrap items-center gap-1.5">
                    <WorkflowActions {...props} />
                </div>
                {/* A saved workflow shows the AI and side panel buttons beside its tabs, and a new one has no tabs yet. */}
                {!isSaved && <SceneTitlePanelButton />}
            </div>
        </div>
    )
}
