import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SaveAsTemplateModal } from './SaveAsTemplateModal'
import { HogFlowManualTriggerButton } from './hogflows/HogFlowManualTriggerButton'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneLogicProps } from './workflowSceneLogic'

export function WorkflowSceneHeader(props: WorkflowSceneLogicProps = {}): JSX.Element {
    const workflowLogicInstance = workflowLogic({ id: props.id })
    const { workflow, workflowChanged, isWorkflowSubmitting, workflowLoading, workflowHasErrors } =
        useValues(workflowLogicInstance)
    const {
        saveWorkflowPartial,
        submitWorkflow,
        discardChanges,
        setWorkflowValue,
        duplicate,
        deleteWorkflow,
        showSaveAsTemplateModal,
    } = useActions(workflowLogicInstance)

    const canCreateTemplates = useFeatureFlag('WORKFLOWS_TEMPLATE_CREATION')

    const isSavedWorkflow = !!(props.id && props.id !== 'new')
    const isCreatedFromTemplate = props.id === 'new'
    const isManualWorkflow = ['manual', 'schedule', 'batch'].includes(workflow?.trigger?.type || '')
    const workflowStatus = workflow?.status
    // TODOdin: Do we need this status thing? Did we have that before?
    const [displayStatus, setDisplayStatus] = useState(workflowStatus)
    const [isTransitioning, setIsTransitioning] = useState(false)
    const prevStatusRef = useRef(workflowStatus)

    useEffect(() => {
        if (workflowStatus !== displayStatus && prevStatusRef.current !== undefined) {
            setIsTransitioning(true)
            const timer = setTimeout(() => {
                setDisplayStatus(workflowStatus)
                setIsTransitioning(false)
            }, 150)
            prevStatusRef.current = workflowStatus
            return () => clearTimeout(timer)
        } else if (workflowStatus !== displayStatus) {
            setDisplayStatus(workflowStatus)
            prevStatusRef.current = workflowStatus
        }
    }, [workflowStatus, displayStatus])

    return (
        <>
            <SaveAsTemplateModal workflowProps={{ ...props }} />
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
                                {workflowStatus !== undefined && displayStatus !== undefined && (
                                    <LemonButton
                                        type={displayStatus === 'active' ? 'primary' : 'secondary'}
                                        onClick={() =>
                                            saveWorkflowPartial({
                                                status: workflowStatus === 'draft' ? 'active' : 'draft',
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
                                )}
                                <>
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
                            <LemonButton type="primary" size="small" onClick={showSaveAsTemplateModal} loading={false}>
                                Save as template
                            </LemonButton>
                        )}
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
                    </>
                }
            />
        </>
    )
}
