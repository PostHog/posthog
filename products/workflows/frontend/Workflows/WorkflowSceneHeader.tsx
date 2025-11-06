import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { HogFlowManualTriggerButton } from './hogflows/HogFlowManualTriggerButton'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneLogicProps } from './workflowSceneLogic'

export const WorkflowSceneHeader = (props: WorkflowSceneLogicProps = {}): JSX.Element => {
    const logic = workflowLogic(props)
    const { workflow, workflowChanged, isWorkflowSubmitting, workflowLoading, workflowHasErrors } = useValues(logic)
    const { saveWorkflowPartial, submitWorkflow, discardChanges, setWorkflowValue } = useActions(logic)

    const isSavedWorkflow = props.id && props.id !== 'new'
    const isManualWorkflow = workflow?.trigger?.type === 'manual'
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
                                    : workflowChanged
                                      ? undefined
                                      : 'No changes to save'
                            }
                        >
                            {props.id === 'new' ? 'Create' : 'Save'}
                        </LemonButton>
                    </>
                }
            />
        </>
    )
}
