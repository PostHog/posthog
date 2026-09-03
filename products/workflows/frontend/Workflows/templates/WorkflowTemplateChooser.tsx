import './WorkflowTemplateChooser.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonDialog } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { HogFlowTemplate } from '../hogflows/types'
import { newWorkflowLogic } from '../newWorkflowLogic'
import { WorkflowTemplateBlankPreview } from './WorkflowTemplateBlankPreview'
import { WorkflowTemplateCard } from './WorkflowTemplateCard'
import { WorkflowTemplateMeta } from './WorkflowTemplateMeta'
import { workflowTemplatesLogic } from './workflowTemplatesLogic'
import { WorkflowTemplateSteps } from './WorkflowTemplateSteps'

interface WorkflowTemplateChooserProps {
    showEmptyWorkflow?: boolean
}

export function WorkflowTemplateChooser(props: WorkflowTemplateChooserProps): JSX.Element {
    const { filteredTemplates, workflowTemplatesLoading } = useValues(workflowTemplatesLogic)
    const { deleteHogflowTemplate } = useActions(workflowTemplatesLogic)
    const { user } = useValues(userLogic)

    const { createWorkflowFromTemplate, createEmptyWorkflow } = useActions(newWorkflowLogic)

    const canEditTemplate = (template: HogFlowTemplate): boolean => {
        if (template.scope === 'global') {
            return user?.is_staff ?? false
        }

        return true
    }

    const canDeleteTemplate = (template: HogFlowTemplate): boolean => {
        // Global templates are managed in code and can't be deleted from the database
        return template.scope !== 'global'
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="WorkflowTemplateChooser">
                {props.showEmptyWorkflow && (
                    <WorkflowTemplateCard
                        name="Blank workflow"
                        description="Start from scratch and add your own trigger and steps."
                        preview={<WorkflowTemplateBlankPreview />}
                        onClick={createEmptyWorkflow}
                        data-attr="create-workflow-blank"
                    />
                )}
                {filteredTemplates.map((template: HogFlowTemplate) => (
                    <WorkflowTemplateCard
                        key={template.id}
                        name={template.name || 'Unnamed template'}
                        description={template.description}
                        preview={<WorkflowTemplateSteps actions={template.actions} />}
                        footer={<WorkflowTemplateMeta template={template} />}
                        onClick={() => createWorkflowFromTemplate(template)}
                        onEdit={
                            canEditTemplate(template)
                                ? () => {
                                      router.actions.push(urls.workflowNew(), {
                                          editTemplateId: template.id,
                                      })
                                  }
                                : undefined
                        }
                        onDelete={
                            canDeleteTemplate(template)
                                ? () => {
                                      LemonDialog.open({
                                          title: 'Delete template?',
                                          description: (
                                              <>
                                                  Are you sure you want to delete "{template.name}"?
                                                  <br />
                                                  This action cannot be undone!
                                              </>
                                          ),
                                          primaryButton: {
                                              children: 'Delete',
                                              status: 'danger',
                                              onClick: async () => {
                                                  try {
                                                      await deleteHogflowTemplate(template)
                                                      lemonToast.success(`Template "${template.name}" deleted`)
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
                                : undefined
                        }
                        data-attr="create-workflow-from-template"
                    />
                ))}
            </div>
            {workflowTemplatesLoading ? (
                <div className="flex justify-center py-6">
                    <Spinner className="text-3xl" />
                </div>
            ) : (
                filteredTemplates.length === 0 && (
                    <p className="mb-0 py-6 text-center text-secondary">
                        No templates match your filters. Clear the search or choose another category.
                    </p>
                )
            )}
        </div>
    )
}
