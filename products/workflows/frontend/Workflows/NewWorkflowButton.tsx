import { useActions } from 'kea'

import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { addProductIntent } from 'lib/utils/product-intents'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { newWorkflowLogic } from './newWorkflowLogic'

export interface NewWorkflowButtonProps {
    size?: LemonButtonProps['size']
    className?: string
    onClick?: () => void
}

export function NewWorkflowButton({ size, className, onClick }: NewWorkflowButtonProps): JSX.Element {
    const { startNewWorkflow } = useActions(newWorkflowLogic)

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LemonButton
                type="primary"
                size={size}
                className={className}
                data-attr="new-workflow"
                onClick={() => {
                    onClick?.()
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
    )
}
