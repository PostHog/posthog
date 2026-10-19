import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'

import { destinationWorkflowSuggestionLogic } from './destinationWorkflowSuggestionLogic'

export function DestinationWorkflowSuggestionModal(): JSX.Element {
    const { template, creatingWorkflow } = useValues(destinationWorkflowSuggestionLogic)
    const { closeSuggestion, continueWithDestination, createWorkflow } = useActions(destinationWorkflowSuggestionLogic)

    return (
        <LemonModal
            isOpen={!!template}
            onClose={closeSuggestion}
            width={480}
            title={
                <div className="flex gap-2 items-center">
                    {template ? (
                        <HogFunctionIcon src={template.icon_url} className={template.icon_class_name} size="small" />
                    ) : null}
                    <span>Create this as a workflow instead?</span>
                </div>
            }
            footer={
                <div className="flex flex-wrap gap-2 justify-end">
                    <LemonButton
                        type="secondary"
                        data-attr="destination-workflow-suggestion-continue"
                        onClick={continueWithDestination}
                        disabledReason={creatingWorkflow ? 'Creating the workflow' : undefined}
                    >
                        Continue with destination
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        data-attr="destination-workflow-suggestion-create"
                        onClick={createWorkflow}
                        loading={creatingWorkflow}
                    >
                        Create workflow
                    </LemonButton>
                </div>
            }
        >
            {template ? (
                <div className="flex flex-col gap-2">
                    <p className="m-0">
                        A workflow can send to {template.name} too. You can also add delays, branches, and email, SMS or
                        push messages around it.
                    </p>
                    <p className="m-0 text-secondary">
                        We'll create a draft workflow with a {template.name} step for you to finish. It stays off until
                        you turn it on.
                    </p>
                </div>
            ) : null}
        </LemonModal>
    )
}
