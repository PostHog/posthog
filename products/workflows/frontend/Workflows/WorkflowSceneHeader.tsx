import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef, useState } from 'react'

import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SaveAsTemplateModal } from './SaveAsTemplateModal'
import { HogFlowManualTriggerButton } from './hogflows/HogFlowManualTriggerButton'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneLogicProps } from './workflowSceneLogic'
import { workflowTemplateLogic } from './workflowTemplateLogic'

export const WorkflowSceneHeader = (props: WorkflowSceneLogicProps = {}): JSX.Element => {
    const logic = workflowLogic(props)
    const { workflow, workflowChanged, isWorkflowSubmitting, workflowLoading, workflowHasErrors, isTemplateEditMode } =
        useValues(logic)
    const { saveWorkflowPartial, submitWorkflow, discardChanges, setWorkflowValue, duplicate, deleteWorkflow } =
        useActions(logic)
    const { searchParams } = useValues(router)
    const editTemplateId = searchParams.editTemplateId as string | undefined
    const templateId = searchParams.templateId as string | undefined
    const templateLogic = workflowTemplateLogic({ ...props, editTemplateId })
    const { showSaveAsTemplateModal } = useActions(templateLogic)
    const canCreateTemplates = useFeatureFlag('WORKFLOWS_TEMPLATE_CREATION')

    const isSavedWorkflow = props.id && props.id !== 'new'
    const isCreatedFromTemplate = props.id === 'new' && !!templateId
    const isManualWorkflow = ['manual', 'schedule', 'batch'].includes(workflow?.trigger?.type || '')
    const [displayStatus, setDisplayStatus] = useState(workflow?.status)
    const [isTransitioning, setIsTransitioning] = useState(false)
    const prevStatusRef = useRef(workflow?.status)

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
                                <More
                                    size="small"
                                    overlay={
                                        <>
                                            <LemonButton fullWidth onClick={() => duplicate()}>
                                                Duplicate
                                            </LemonButton>
                                            <LemonDivider />
                                            <LemonButton status="danger" fullWidth onClick={() => deleteWorkflow()}>
                                                Delete
                                            </LemonButton>
                                        </>
                                    }
                                />
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
                        {canCreateTemplates && (
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={showSaveAsTemplateModal}
                                loading={isTemplateEditMode && isWorkflowSubmitting}
                            >
                                {isTemplateEditMode ? 'Update template' : 'Save as template'}
                            </LemonButton>
                        )}
                        {!isTemplateEditMode && (
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
