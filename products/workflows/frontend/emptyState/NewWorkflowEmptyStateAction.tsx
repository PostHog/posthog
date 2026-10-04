import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { addProductIntent } from 'lib/utils/product-intents'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { newWorkflowLogic } from '../Workflows/newWorkflowLogic'
import { NewWorkflowModal } from '../Workflows/NewWorkflowModal'

export function NewWorkflowEmptyStateAction({ onClick }: { onClick: () => void }): JSX.Element {
    const { startNewWorkflow } = useActions(newWorkflowLogic)

    return (
        <>
            <AccessControlAction
                resourceType={AccessControlResourceType.Workflow}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton
                    type="primary"
                    className="self-start"
                    data-attr="new-workflow"
                    onClick={() => {
                        onClick()
                        void addProductIntent({
                            product_type: ProductKey.WORKFLOWS,
                            intent_context: ProductIntentContext.WORKFLOW_CREATED,
                        })
                        startNewWorkflow()
                    }}
                >
                    New workflow
                </LemonButton>
            </AccessControlAction>
            <NewWorkflowModal />
        </>
    )
}
