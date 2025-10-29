import { useActions, useValues } from 'kea'

import { IconButton } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { workflowLogic } from './workflowLogic'
import { WorkflowSceneLogicProps } from './workflowSceneLogic'

export const WorkflowSceneHeader = (props: WorkflowSceneLogicProps = {}): JSX.Element => {
    const logic = workflowLogic(props)
    const { workflow, workflowChanged, isWorkflowSubmitting, workflowLoading, workflowHasErrors } = useValues(logic)
    const { saveWorkflowPartial, submitWorkflow, discardChanges, setWorkflowValue, triggerManualWorkflow } =
        useActions(logic)

    const isSavedWorkflow = props.id && props.id !== 'new'
    const isManualWorkflow = workflow?.trigger?.type === 'manual'

    return (
        <>
            <SceneTitleSection
                name={workflow?.name}
                description={workflow?.description}
                resourceType={{ type: 'workflows' }}
                canEdit
                onNameChange={(name) => setWorkflowValue('name', name)}
                onDescriptionChange={(description) => setWorkflowValue('description', description)}
                isLoading={workflowLoading}
                renameDebounceMs={200}
                actions={
                    <>
                        {isManualWorkflow && (
                            <LemonButton
                                type="primary"
                                disabledReason={workflow?.status !== 'active' && 'Must enable workflow to use trigger'}
                                icon={<IconButton />}
                                tooltip="Triggers workflow immediately"
                                onClick={triggerManualWorkflow}
                            >
                                Trigger
                            </LemonButton>
                        )}
                        {isSavedWorkflow && (
                            <>
                                <LemonButton
                                    type="primary"
                                    onClick={() =>
                                        saveWorkflowPartial({
                                            status: workflow?.status === 'draft' ? 'active' : 'draft',
                                        })
                                    }
                                    size="small"
                                    loading={workflowLoading}
                                    disabledReason={workflowChanged ? 'Save changes first' : undefined}
                                >
                                    {workflow?.status === 'draft' ? 'Enable' : 'Disable'}
                                </LemonButton>
                            </>
                        )}

                        {isSavedWorkflow && workflowChanged && (
                            <>
                                <LemonButton
                                    data-attr="discard-workflow-changes"
                                    type="secondary"
                                    onClick={() => discardChanges()}
                                    size="small"
                                >
                                    Discard changes
                                </LemonButton>
                            </>
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
