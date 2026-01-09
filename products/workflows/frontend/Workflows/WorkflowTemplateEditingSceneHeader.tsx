import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { UpdateTemplateModal } from './UpdateTemplateModal'
import { HogFlowManualTriggerButton } from './hogflows/HogFlowManualTriggerButton'
import { WorkflowSceneLogicProps } from './workflowSceneLogic'
import { workflowTemplateEditingLogic } from './workflowTemplateEditingLogic'

interface WorkflowTemplateEditingSceneHeaderProps {
    editTemplateId: string
    workflowProps?: WorkflowSceneLogicProps
}

export function WorkflowTemplateEditingSceneHeader({
    editTemplateId,
    workflowProps = {},
}: WorkflowTemplateEditingSceneHeaderProps): JSX.Element {
    const templateEditingLogic = workflowTemplateEditingLogic({ editTemplateId })
    const { template, templateLoading, workflowTemplateChanged, isWorkflowTemplateSubmitting } =
        useValues(templateEditingLogic)
    const { discardChanges, setWorkflowTemplateValues } = useActions(templateEditingLogic)

    const { showUpdateTemplateModal } = useActions(templateEditingLogic)
    const canCreateTemplates = useFeatureFlag('WORKFLOWS_TEMPLATE_CREATION')

    const isManualWorkflow = ['manual', 'schedule', 'batch'].includes(template?.trigger?.type || '')

    return (
        <>
            <UpdateTemplateModal templateProps={{ editTemplateId }} />
            <SceneTitleSection
                name={template?.name}
                description={template?.description}
                resourceType={{ type: 'workflows' }}
                canEdit
                onNameChange={(name) => setWorkflowTemplateValues({ name })}
                onDescriptionChange={(description) => setWorkflowTemplateValues({ description })}
                isLoading={templateLoading && !template}
                renameDebounceMs={200}
                actions={
                    <>
                        {isManualWorkflow && <HogFlowManualTriggerButton {...workflowProps} />}
                        {workflowTemplateChanged && (
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
                                onClick={showUpdateTemplateModal}
                                loading={isWorkflowTemplateSubmitting}
                            >
                                Update template
                            </LemonButton>
                        )}
                    </>
                }
            />
        </>
    )
}
