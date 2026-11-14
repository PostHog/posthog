import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { addProductIntent } from 'lib/utils/product-intents'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { newWorkflowLogic } from '../newWorkflowLogic'
import { workflowTemplatesLogic } from '../templates/workflowTemplatesLogic'
import { workflowFoldersLogic } from './workflowFoldersLogic'
import { workflowsListV2Logic } from './workflowsListV2Logic'

export function WorkflowNewWorkflowButton(): JSX.Element {
    const { currentFolder } = useValues(workflowFoldersLogic)
    const { templateTypeFilter } = useValues(workflowsListV2Logic)
    const { setTypeFilter } = useActions(workflowTemplatesLogic)
    const { startNewWorkflow } = useActions(newWorkflowLogic)
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LemonButton
                type="primary"
                size="small"
                onClick={() => {
                    void addProductIntent({
                        product_type: ProductKey.WORKFLOWS,
                        intent_context: ProductIntentContext.WORKFLOW_CREATED,
                    })
                    setTypeFilter(templateTypeFilter)
                    startNewWorkflow()
                }}
                tooltip={`The workflow lands in ${currentFolder && currentFolder !== 'Unfiled' ? currentFolder.replaceAll('/', ' / ') : 'Unfiled / Workflows'}`}
                data-attr="new-workflow"
            >
                New workflow
            </LemonButton>
        </AccessControlAction>
    )
}
