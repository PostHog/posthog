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
    const { workflow, workflowChanged, isWorkflowSubmitting, workflowLoading, workflowHasErrors } = useValues(logic)
    const { saveWorkflowPartial, submitWorkflow, discardChanges, setWorkflowValue, duplicate, archiveWorkflow } =
        useActions(logic)
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
                onNameChange={(name) => setWorkflowValue('name', name)}
                onDescriptionChange={(description) => setWorkflowValue('description', description)}
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
                                    disabledReason={workflowChanged ? 'Save changes first' : undefined}
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
                        {workflowChanged && (
                            <LemonButton
                                data-attr="discard-workflow-changes"
                                type="secondary"
                                onClick={() => discardChanges()}
                                size="small"
                            >
                                Clear changes
                            </LemonButton>
                        )}
                        {editTemplateId ? (
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={showSaveAsTemplateModal}
                                loading={isWorkflowSubmitting}
                            >
                                Update template
                            </LemonButton>
                        ) : (
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
                                          : workflowChanged
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
