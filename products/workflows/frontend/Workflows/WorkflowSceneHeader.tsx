import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArchive, IconClock, IconCopy, IconScreen, IconTrash, IconUpload } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { SceneTagsCombobox } from 'lib/components/Scenes/SceneTagsCombobox'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarPopover,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowSuggestionsAvailabilityLogic } from './suggestions/workflowSuggestionsAvailabilityLogic'
import { WorkflowSuggestionsMenuItem } from './suggestions/WorkflowSuggestionsMenuItem'
import { SaveAsTemplateModal } from './templates/SaveAsTemplateModal'
import { workflowTemplateLogic } from './templates/workflowTemplateLogic'
import { canEditWorkflow } from './workflowAccess'
import { WorkflowActions } from './WorkflowActions'
import { workflowBackTo } from './workflowBackTo'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneLogicProps } from './workflowSceneLogic'
import { WorkflowScenePanel } from './WorkflowScenePanel'

export const WorkflowSceneHeader = (props: WorkflowSceneLogicProps = {}): JSX.Element => {
    const { workflow, hasUnsavedChanges, hasStagedDraft, workflowLoading, workflowUserAccessLevel } =
        useValues(workflowLogic)
    const { setWorkflowValue, duplicate, archiveWorkflow, publishDraft, discardDraft } = useActions(workflowLogic)
    const { searchParams } = useValues(router)
    const editTemplateId = searchParams.editTemplateId as string | undefined
    const { showSaveAsTemplateModal } = useActions(workflowTemplateLogic({ ...props, editTemplateId }))

    const isSavedWorkflow = props.id && props.id !== 'new'
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]
    const { suggestionsAvailable } = useValues(workflowSuggestionsAvailabilityLogic)
    const canEdit = canEditWorkflow(workflow, workflowUserAccessLevel)

    return (
        <>
            <SaveAsTemplateModal {...props} editTemplateId={editTemplateId} />
            {sceneMenuBarEnabled && isSavedWorkflow && (
                <SceneMenuBar>
                    <SceneMenuBarMenu label="File" dataAttr="workflow-menubar-file">
                        <SceneMenuBarFileItems dataAttrKey="workflow" />
                        <SceneMenuBarSeparator />
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Workflow}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={workflowUserAccessLevel ?? undefined}
                        >
                            {({ disabledReason }) => (
                                <SceneMenuBarItem
                                    variant="destructive"
                                    onClick={() => archiveWorkflow(workflow)}
                                    data-attr="workflow-menubar-archive"
                                    disabled={!!disabledReason}
                                    tooltip={disabledReason ?? undefined}
                                >
                                    <IconArchive />
                                    Archive
                                </SceneMenuBarItem>
                            )}
                        </AccessControlAction>
                    </SceneMenuBarMenu>
                    <SceneMenuBarMenu label="Edit" dataAttr="workflow-menubar-edit">
                        <SceneMenuBarItem onClick={() => duplicate()} data-attr="workflow-menubar-duplicate">
                            <IconCopy />
                            Duplicate
                        </SceneMenuBarItem>
                        <SceneMenuBarItem
                            opensFloatingUi
                            onClick={showSaveAsTemplateModal}
                            data-attr="workflow-menubar-save-as-template"
                        >
                            <IconScreen />
                            Save as template
                        </SceneMenuBarItem>
                        {hasStagedDraft && (
                            <>
                                <SceneMenuBarSeparator />
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Workflow}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={workflowUserAccessLevel ?? undefined}
                                >
                                    {({ disabledReason }) => (
                                        <SceneMenuBarItem
                                            opensFloatingUi
                                            onClick={() => publishDraft()}
                                            data-attr="workflow-menubar-publish-draft"
                                            disabled={!!disabledReason || hasUnsavedChanges}
                                            tooltip={
                                                disabledReason ??
                                                (hasUnsavedChanges
                                                    ? 'Save or clear your in-progress edits first'
                                                    : undefined)
                                            }
                                        >
                                            <IconUpload />
                                            Publish draft
                                        </SceneMenuBarItem>
                                    )}
                                </AccessControlAction>
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Workflow}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={workflowUserAccessLevel ?? undefined}
                                >
                                    {({ disabledReason }) => (
                                        <SceneMenuBarItem
                                            variant="destructive"
                                            onClick={() => discardDraft()}
                                            data-attr="workflow-menubar-discard-draft"
                                            disabled={!!disabledReason || hasUnsavedChanges}
                                            tooltip={
                                                disabledReason ??
                                                (hasUnsavedChanges
                                                    ? 'Save or clear your in-progress edits first'
                                                    : undefined)
                                            }
                                        >
                                            <IconTrash />
                                            Discard draft
                                        </SceneMenuBarItem>
                                    )}
                                </AccessControlAction>
                            </>
                        )}
                    </SceneMenuBarMenu>
                    <SceneMenuBarMenu label="View" dataAttr="workflow-menubar-view">
                        <SceneMenuBarItem
                            onClick={() => router.actions.push(urls.workflow(props.id!, 'history'))}
                            data-attr="workflow-menubar-version-history"
                        >
                            <IconClock />
                            Version history
                        </SceneMenuBarItem>
                        {suggestionsAvailable && (
                            <>
                                <SceneMenuBarSeparator />
                                <WorkflowSuggestionsMenuItem id={props.id!} />
                            </>
                        )}
                    </SceneMenuBarMenu>
                    <SceneMenuBarPopover
                        label="Metadata"
                        dataAttr="workflow-menubar-metadata"
                        contentClassName="w-80 p-2 flex flex-col gap-2"
                    >
                        <SceneTagsCombobox
                            onSave={(tags) => setWorkflowValue('tags', tags)}
                            canEdit={canEdit}
                            tags={workflow?.tags ?? []}
                            dataAttrKey="workflow"
                        />
                    </SceneMenuBarPopover>
                </SceneMenuBar>
            )}
            <SceneTitleSection
                name={workflow?.name}
                description={workflow?.description}
                resourceType={{ type: 'workflows' }}
                canEdit
                onNameChange={(name) => setWorkflowValue('name', name)}
                onDescriptionChange={(description) => setWorkflowValue('description', description)}
                isLoading={workflowLoading && !workflow}
                renameDebounceMs={200}
                forceBackTo={workflowBackTo(workflow, props.id)}
                actions={
                    <>
                        <WorkflowActions {...props} />
                        {isSavedWorkflow && <WorkflowScenePanel {...props} />}
                    </>
                }
            />
        </>
    )
}
