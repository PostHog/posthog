import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef, useState } from 'react'

import { IconArchive, IconCopy, IconScreen } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { ScenePanel, ScenePanelActionsSection, ScenePanelDivider } from '~/layout/scenes/SceneLayout'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { HogFlowManualTriggerButton } from './hogflows/HogFlowManualTriggerButton'
import { SaveAsTemplateModal } from './templates/SaveAsTemplateModal'
import { workflowTemplateLogic } from './templates/workflowTemplateLogic'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneLogicProps } from './workflowSceneLogic'

export const WorkflowSceneHeader = (props: WorkflowSceneLogicProps = {}): JSX.Element => {
    const logic = workflowLogic(props)
    const {
        workflow,
        workflowContentChanged,
        isWorkflowSubmitting,
        workflowLoading,
        workflowHasErrors,
        workflowHasActionErrors,
        hasPendingDraft,
        isDraftSaving,
        isDraftPublishing,
        canPublish,
    } = useValues(logic)
    const {
        saveWorkflowPartial,
        submitWorkflow,
        setWorkflowValue,
        saveMetadataField,
        duplicate,
        archiveWorkflow,
        saveDraftNow,
        publishWorkflow,
        discardDraft,
    } = useActions(logic)
    const { searchParams } = useValues(router)
    const editTemplateId = searchParams.editTemplateId as string | undefined
    const templateId = searchParams.templateId as string | undefined
    const templateLogic = workflowTemplateLogic({ ...props, editTemplateId })
    const { showSaveAsTemplateModal } = useActions(templateLogic)

    const isSavedWorkflow = props.id && props.id !== 'new'
    const isCreatedFromTemplate = props.id === 'new' && !!templateId
    const isManualWorkflow = ['manual', 'schedule', 'batch'].includes(workflow?.trigger?.type || '')
    const [displayStatus, setDisplayStatus] = useState(workflow?.status)
    const [isTransitioning, setIsTransitioning] = useState(false)
    const prevStatusRef = useRef(workflow?.status)
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

    const isActive = workflow?.status === 'active'

    useEffect(() => {
        // Only transition if status actually changed (not on initial mount)
        if (workflow?.status !== displayStatus && prevStatusRef.current !== undefined) {
            setIsTransitioning(true)
            const timer = setTimeout(() => {
                setDisplayStatus(workflow?.status)
                setIsTransitioning(false)
            }, 150)
            prevStatusRef.current = workflow?.status
            return () => clearTimeout(timer)
        } else if (workflow?.status !== displayStatus) {
            // On initial mount, just set it without transition
            setDisplayStatus(workflow?.status)
            prevStatusRef.current = workflow?.status
        }
    }, [workflow?.status, displayStatus])

    return (
        <>
            <SaveAsTemplateModal {...props} editTemplateId={editTemplateId} />
            <SceneTitleSection
                name={workflow?.name}
                description={workflow?.description}
                resourceType={{ type: 'workflows' }}
                canEdit
                onNameChange={(name) => {
                    setWorkflowValue('name', name)
                    saveMetadataField('name', name)
                }}
                onDescriptionChange={(description) => {
                    setWorkflowValue('description', description)
                    saveMetadataField('description', description)
                }}
                isLoading={workflowLoading && !workflow}
                renameDebounceMs={200}
                actions={
                    <>
                        {isManualWorkflow && <HogFlowManualTriggerButton {...props} />}
                        {isSavedWorkflow && (
                            <>
                                <LemonButton
                                    type={displayStatus === 'active' ? 'primary' : 'secondary'}
                                    onClick={() =>
                                        saveWorkflowPartial({
                                            status: workflow?.status === 'draft' ? 'active' : 'draft',
                                        })
                                    }
                                    size="small"
                                    disabledReason={
                                        hasPendingDraft
                                            ? 'Publish or discard draft first'
                                            : workflowContentChanged
                                              ? 'Save changes first'
                                              : workflow?.status === 'draft' && workflowHasActionErrors
                                                ? 'Fix all errors before enabling'
                                                : undefined
                                    }
                                    className="transition-colors duration-300 ease-in-out"
                                    data-attr="workflow-launch"
                                >
                                    <span
                                        className={`inline-block transition-opacity duration-300 ease-in-out ${
                                            isTransitioning ? 'opacity-0' : 'opacity-100'
                                        }`}
                                    >
                                        {displayStatus === 'draft' ? 'Enable' : 'Disable'}
                                    </span>
                                </LemonButton>
                                <LemonDivider vertical />
                                {isRemovingSidePanelFlag ? (
                                    <ScenePanel>
                                        <ScenePanelActionsSection>
                                            <ButtonPrimitive menuItem onClick={() => duplicate()}>
                                                <IconCopy />
                                                Duplicate
                                            </ButtonPrimitive>
                                            <ButtonPrimitive menuItem onClick={showSaveAsTemplateModal}>
                                                <IconScreen />
                                                Save as template
                                            </ButtonPrimitive>
                                        </ScenePanelActionsSection>
                                        <ScenePanelDivider />
                                        <ScenePanelActionsSection>
                                            <ButtonPrimitive
                                                menuItem
                                                onClick={() => archiveWorkflow(workflow)}
                                                variant="danger"
                                            >
                                                <IconArchive />
                                                Archive
                                            </ButtonPrimitive>
                                        </ScenePanelActionsSection>
                                    </ScenePanel>
                                ) : (
                                    <More
                                        size="small"
                                        overlay={
                                            <>
                                                <LemonButton fullWidth onClick={() => duplicate()}>
                                                    Duplicate
                                                </LemonButton>
                                                <LemonButton fullWidth onClick={showSaveAsTemplateModal}>
                                                    Save as template
                                                </LemonButton>
                                                <LemonDivider />
                                                <LemonButton
                                                    status="danger"
                                                    fullWidth
                                                    onClick={() => archiveWorkflow(workflow)}
                                                >
                                                    Archive
                                                </LemonButton>
                                            </>
                                        }
                                    />
                                )}
                            </>
                        )}
                        {isSavedWorkflow && (hasPendingDraft || workflowContentChanged) ? (
                            <LemonButton
                                data-attr="discard-draft"
                                type="secondary"
                                onClick={() => discardDraft()}
                                size="small"
                            >
                                Discard changes
                            </LemonButton>
                        ) : null}
                        {editTemplateId ? (
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={showSaveAsTemplateModal}
                                loading={isWorkflowSubmitting}
                            >
                                Update template
                            </LemonButton>
                        ) : isActive && hasPendingDraft ? (
                            /* Active workflow with draft: show Publish as primary action */
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={publishWorkflow}
                                loading={isDraftPublishing}
                                disabledReason={!canPublish ? 'Fix all errors before publishing' : undefined}
                                data-attr="publish-workflow"
                            >
                                Publish
                            </LemonButton>
                        ) : isActive && workflowContentChanged ? (
                            /* Active workflow with content changes but no draft yet: offer Save draft */
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={saveDraftNow}
                                loading={isDraftSaving}
                                data-attr="save-draft"
                            >
                                Save draft
                            </LemonButton>
                        ) : (
                            /* Default: normal Save/Create button */
                            <LemonButton
                                type="primary"
                                size="small"
                                htmlType="submit"
                                form="workflow"
                                onClick={submitWorkflow}
                                loading={isWorkflowSubmitting}
                                disabledReason={
                                    workflowHasErrors
                                        ? 'Some fields still need work'
                                        : isCreatedFromTemplate
                                          ? undefined
                                          : workflowContentChanged
                                            ? undefined
                                            : 'No changes to save'
                                }
                            >
                                {props.id === 'new' ? 'Create as draft' : 'Save'}
                            </LemonButton>
                        )}
                    </>
                }
            />
        </>
    )
}
