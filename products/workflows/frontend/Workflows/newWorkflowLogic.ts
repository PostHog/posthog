import { actions, kea, listeners, path, reducers } from 'kea'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import type { HogFlowTemplate } from './hogflows/types'
import type { newWorkflowLogicType } from './newWorkflowLogicType'

export const newWorkflowLogic = kea<newWorkflowLogicType>([
    path(['products', 'workflows', 'frontend', 'newWorkflowLogic']),
    actions({
        showNewWorkflowModal: true,
        hideNewWorkflowModal: true,
        createWorkflowFromTemplate: (template: HogFlowTemplate) => ({ template }),
        createEmptyWorkflow: true,
    }),
    reducers({
        newWorkflowModalVisible: [
            false,
            {
                showNewWorkflowModal: () => true,
                hideNewWorkflowModal: () => false,
            },
        ],
    }),
    listeners(({ actions }) => ({
        createWorkflowFromTemplate: ({ template }) => {
            actions.hideNewWorkflowModal()
            router.actions.push(urls.workflowNew(), { templateId: template.id })
        },
        createEmptyWorkflow: () => {
            actions.hideNewWorkflowModal()
            router.actions.push(urls.workflowNew())
        },
    })),
])
