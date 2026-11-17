import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import {
    IconArchive,
    IconClock,
    IconCopy,
    IconPause,
    IconPlay,
    IconPlayFilled,
    IconScreen,
    IconTrash,
    IconUndo,
    IconUpload,
} from '@posthog/icons'

import { SceneTagsCombobox } from 'lib/components/Scenes/SceneTagsCombobox'
import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { HogFlowManualTriggerButton } from './hogflows/HogFlowManualTriggerButton'
import { hogFlowManualTriggerButtonLogic } from './hogflows/HogFlowManualTriggerButtonLogic'
import { useWorkflowSuggestionsAction } from './suggestions/useWorkflowSuggestionsAction'
import { workflowSuggestionsAvailabilityLogic } from './suggestions/workflowSuggestionsAvailabilityLogic'
import { workflowTemplateLogic } from './templates/workflowTemplateLogic'
import { canEditWorkflow } from './workflowAccess'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneLogicProps } from './workflowSceneLogic'

const RESOURCE_TYPE = 'workflow'
const UNSAVED_EDITS_REASON = 'Save or clear your in-progress edits first'

type SavedWorkflowProps = WorkflowSceneLogicProps & { id: string }

/** The saved workflow's menu bar. The caller renders it only behind the scene menu bar flag. */
export function WorkflowSceneMenuBar(props: SavedWorkflowProps): JSX.Element {
    const { suggestionsAvailable } = useValues(workflowSuggestionsAvailabilityLogic)
    return suggestionsAvailable ? (
        <WorkflowSceneMenuBarWithSuggestions {...props} />
    ) : (
        <WorkflowSceneMenuBarActions {...props} suggestionActions={[]} />
    )
}

function WorkflowSceneMenuBarWithSuggestions(props: SavedWorkflowProps): JSX.Element {
    const suggestionAction = useWorkflowSuggestionsAction(props.id, { section: 'suggestions' })
    return <WorkflowSceneMenuBarActions {...props} suggestionActions={[suggestionAction]} />
}

function WorkflowSceneMenuBarActions({
    suggestionActions,
    ...props
}: SavedWorkflowProps & { suggestionActions: SceneAction[] }): JSX.Element {
    const {
        workflow,
        hasUnsavedChanges,
        hasStagedDraft,
        showDraftActions,
        isWorkflowSubmitting,
        workflowHasErrors,
        workflowUserAccessLevel,
        publishDisabledReason,
        discardDisabledReason,
        statusToggleDisabledReason,
        manualTriggerDisabledReason,
    } = useValues(workflowLogic)
    const {
        setWorkflowValue,
        duplicate,
        archiveWorkflow,
        publishDraft,
        discardDraft,
        discardChanges,
        submitWorkflow,
        saveWorkflowPartial,
    } = useActions(workflowLogic)
    const { searchParams } = useValues(router)
    const editTemplateId = searchParams.editTemplateId as string | undefined
    const { showSaveAsTemplateModal } = useActions(workflowTemplateLogic({ ...props, editTemplateId }))
    const { setPopoverVisible } = useActions(hogFlowManualTriggerButtonLogic(props))
    const fileActions = useSceneFileActions(RESOURCE_TYPE)

    const canEdit = canEditWorkflow(workflow, workflowUserAccessLevel)
    const accessDisabledReason =
        getAccessControlDisabledReason(
            AccessControlResourceType.Workflow,
            AccessControlLevel.Editor,
            workflowUserAccessLevel ?? undefined
        ) ?? undefined
    const isManualWorkflow = ['manual', 'batch'].includes(workflow?.trigger?.type || '')
    const active = workflow?.status === 'active'
    const enabled = workflow?.status !== 'draft'
    const publishIsPrimary = hasStagedDraft && !hasUnsavedChanges
    const saveDisabledReason =
        accessDisabledReason ??
        (isWorkflowSubmitting
            ? 'Saving workflow'
            : workflowHasErrors
              ? 'Some fields still need work'
              : hasUnsavedChanges
                ? undefined
                : 'No changes to save')

    const actions: SceneAction[] = [
        ...fileActions,
        ...(isManualWorkflow
            ? ([
                  {
                      group: 'file',
                      section: 'run',
                      id: `${RESOURCE_TYPE}-menubar-trigger`,
                      label: 'Trigger',
                      icon: <IconPlayFilled />,
                      opensFloatingUi: true,
                      disabledReason: manualTriggerDisabledReason,
                      onSelect: () => setPopoverVisible(true),
                      pinned: {
                          order: 0,
                          variant: 'secondary',
                          render: () => <HogFlowManualTriggerButton {...props} />,
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'file',
            section: 'delete',
            id: `${RESOURCE_TYPE}-menubar-archive`,
            label: 'Archive',
            icon: <IconArchive />,
            destructive: true,
            disabledReason: accessDisabledReason,
            onSelect: () => archiveWorkflow(workflow),
        },
        editTemplateId
            ? {
                  group: 'edit',
                  section: 'save',
                  id: `${RESOURCE_TYPE}-menubar-update-template`,
                  label: 'Update template',
                  icon: <IconScreen />,
                  opensFloatingUi: true,
                  disabledReason: isWorkflowSubmitting ? 'Saving workflow' : undefined,
                  onSelect: showSaveAsTemplateModal,
                  pinned: { order: 3, variant: 'primary' },
              }
            : {
                  group: 'edit',
                  section: 'save',
                  id: `${RESOURCE_TYPE}-menubar-save`,
                  label: active ? 'Save draft' : 'Save',
                  disabledReason: saveDisabledReason,
                  onSelect: submitWorkflow,
                  pinned: {
                      order: 3,
                      variant: publishIsPrimary ? 'secondary' : 'primary',
                      dataAttr: 'workflow-save',
                  },
              },
        ...(hasUnsavedChanges
            ? ([
                  {
                      group: 'edit',
                      section: 'save',
                      id: `${RESOURCE_TYPE}-menubar-clear-changes`,
                      label: 'Clear changes',
                      icon: <IconUndo />,
                      onSelect: () => discardChanges(),
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'edit',
            section: 'state',
            id: `${RESOURCE_TYPE}-menubar-enabled`,
            label: enabled ? 'Disable' : 'Enable',
            icon: enabled ? <IconPause /> : <IconPlay />,
            disabledReason: accessDisabledReason ?? statusToggleDisabledReason,
            onSelect: () => saveWorkflowPartial({ status: enabled ? 'draft' : 'active' }),
            pinned: { order: 1, variant: 'secondary', dataAttr: 'workflow-launch' },
        },
        {
            group: 'edit',
            id: `${RESOURCE_TYPE}-menubar-duplicate`,
            label: 'Duplicate',
            icon: <IconCopy />,
            onSelect: () => duplicate(),
        },
        {
            group: 'edit',
            id: `${RESOURCE_TYPE}-menubar-save-as-template`,
            label: 'Save as template',
            icon: <IconScreen />,
            opensFloatingUi: true,
            onSelect: showSaveAsTemplateModal,
        },
        ...(!editTemplateId && (hasStagedDraft || showDraftActions)
            ? ([
                  {
                      group: 'edit',
                      section: 'draft',
                      id: `${RESOURCE_TYPE}-menubar-publish-draft`,
                      label: 'Publish draft',
                      icon: <IconUpload />,
                      opensFloatingUi: true,
                      disabledReason:
                          accessDisabledReason ??
                          publishDisabledReason ??
                          (hasUnsavedChanges ? UNSAVED_EDITS_REASON : undefined),
                      onSelect: () => publishDraft(),
                      pinned: {
                          order: 2,
                          variant: publishIsPrimary ? 'primary' : 'secondary',
                          dataAttr: 'workflow-publish',
                      },
                  },
                  {
                      group: 'edit',
                      section: 'draft',
                      id: `${RESOURCE_TYPE}-menubar-discard-draft`,
                      label: 'Discard draft',
                      icon: <IconTrash />,
                      destructive: true,
                      disabledReason:
                          accessDisabledReason ??
                          discardDisabledReason ??
                          (hasUnsavedChanges ? UNSAVED_EDITS_REASON : undefined),
                      onSelect: () => discardDraft(),
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-version-history`,
            label: 'Version history',
            icon: <IconClock />,
            onSelect: () => router.actions.push(urls.workflow(props.id, 'history')),
        },
        ...suggestionActions,
        {
            group: 'metadata',
            type: 'panel',
            id: `${RESOURCE_TYPE}-menubar-metadata`,
            label: 'Metadata',
            render: () => (
                <SceneTagsCombobox
                    onSave={(tags) => setWorkflowValue('tags', tags)}
                    canEdit={canEdit}
                    tags={workflow?.tags ?? []}
                    dataAttrKey={RESOURCE_TYPE}
                />
            ),
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
