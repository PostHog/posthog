import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconCopy, IconTrash } from '@posthog/icons'
import { LemonDialog, LemonDivider, SpinnerOverlay } from '@posthog/lemon-ui'

import api from 'lib/api'
import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SaveAsTemplateModal } from './SaveAsTemplateModal'
import { HogFlowEditor } from './hogflows/HogFlowEditor'
import { workflowLogic } from './workflowLogic'
import { workflowTemplateLogic } from './workflowTemplateLogic'

export interface WorkflowTemplateSceneProps {
    templateId: string
}

export const scene: SceneExport<WorkflowTemplateSceneProps> = {
    component: WorkflowTemplateScene,
    paramsToProps: ({ params: { templateId } }) => ({
        templateId,
    }),
}

export function WorkflowTemplateScene({ templateId }: WorkflowTemplateSceneProps): JSX.Element {
    // Force remount when templateId changes by using it as a key
    return <WorkflowTemplateSceneInner key={templateId} templateId={templateId} />
}

function WorkflowTemplateSceneInner({ templateId }: WorkflowTemplateSceneProps): JSX.Element {
    const canEditTemplates = useFeatureFlag('WORKFLOWS_TEMPLATE_CREATION')
    
    // Initialize the workflow logic with the template - keep id as 'new' but use templateId for loading
    const logic = workflowLogic({ id: 'new', templateId, isEditingTemplate: true })
    const { workflow, workflowLoading, originalWorkflow, workflowChanged } = useValues(logic)
    const { setWorkflowValue, loadWorkflow } = useActions(logic)
    
    const templateLogic = workflowTemplateLogic({ id: 'new', templateId })
    const { showUpdateTemplateModal, setEditingTemplateId } = useActions(templateLogic)
    
    // Reload workflow when templateId changes
    useEffect(() => {
        loadWorkflow()
    }, [templateId])
    
    if (!originalWorkflow && workflowLoading) {
        return <SpinnerOverlay sceneLevel />
    }

    if (!originalWorkflow) {
        return <NotFound object="workflow template" />
    }
    
    if (!canEditTemplates) {
        return <NotFound object="workflow template" />
    }

    const handleUpdateTemplate = async (): Promise<void> => {
        if (!workflow) {
            lemonToast.error('Workflow not loaded')
            return
        }

        try {
            const template = await api.hogFlowTemplates.getHogFlowTemplate(templateId)
            templateLogic.actions.setTemplateFormValues({
                name: workflow.name || template.name || '',
                description: workflow.description || template.description || '',
                image_url: template.image_url || null,
                scope: template.scope || 'team',
            })
            setEditingTemplateId(templateId)
            showUpdateTemplateModal()
        } catch (error) {
            templateLogic.actions.setTemplateFormValues({
                name: workflow.name || '',
                description: workflow.description || '',
                image_url: null,
                scope: 'team',
            })
            setEditingTemplateId(templateId)
            showUpdateTemplateModal()
        }
    }

    const handleDeleteTemplate = (): void => {
        LemonDialog.open({
            title: 'Delete template?',
            description: (
                <>
                    Are you sure you want to delete "{workflow?.name}"?
                    <br />
                    This action cannot be undone.
                </>
            ),
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: async () => {
                    try {
                        await api.hogFlowTemplates.deleteHogFlowTemplate(templateId)
                        lemonToast.success('Template deleted successfully')
                        router.actions.push(urls.workflows())
                    } catch (error: any) {
                        lemonToast.error(
                            `Failed to delete template: ${error.detail || error.message || 'Unknown error'}`
                        )
                    }
                },
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const handleDuplicateTemplate = async (): Promise<void> => {
        if (!workflow) {
            lemonToast.error('Workflow not loaded')
            return
        }

        try {
            const newTemplate = await api.hogFlowTemplates.createHogFlowTemplate({
                ...workflow,
                name: `${workflow.name} (copy)`,
                description: workflow.description || '',
            })
            
            if (newTemplate?.id) {
                lemonToast.success('Template duplicated successfully')
                // Navigate to the new template
                router.actions.push(urls.workflowTemplate(newTemplate.id))
            } else {
                throw new Error('Template created but no ID returned')
            }
        } catch (error: any) {
            lemonToast.error(
                `Failed to duplicate template: ${error.detail || error.message || 'Unknown error'}`
            )
        }
    }

    return (
        <SceneContent className="flex flex-col">
            <SaveAsTemplateModal id="new" templateId={templateId} />
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
                        <More
                            size="small"
                            overlay={
                                <>
                                    <LemonButton
                                        fullWidth
                                        onClick={handleDuplicateTemplate}
                                        icon={<IconCopy />}
                                    >
                                        Duplicate
                                    </LemonButton>
                                    <LemonDivider />
                                    <LemonButton
                                        status="danger"
                                        fullWidth
                                        onClick={handleDeleteTemplate}
                                        icon={<IconTrash />}
                                    >
                                        Delete
                                    </LemonButton>
                                </>
                            }
                        />
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => router.actions.push(urls.workflows())}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={handleUpdateTemplate}
                            disabledReason={!workflowChanged ? 'No changes to save' : undefined}
                        >
                            Update template
                        </LemonButton>
                    </>
                }
            />
            <div className="relative border rounded-md h-[calc(100vh-280px)]">
                <BindLogic logic={workflowLogic} props={{ id: 'new', templateId, isEditingTemplate: true }}>
                    <HogFlowEditor />
                </BindLogic>
            </div>
        </SceneContent>
    )
}