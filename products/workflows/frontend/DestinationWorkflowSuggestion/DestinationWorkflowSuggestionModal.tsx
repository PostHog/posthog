import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'

import { destinationWorkflowSuggestionLogic } from './destinationWorkflowSuggestionLogic'

export function DestinationWorkflowSuggestionModal(): JSX.Element {
    const { template } = useValues(destinationWorkflowSuggestionLogic)
    const { closeSuggestion, continueWithDestination, openWorkflows } = useActions(destinationWorkflowSuggestionLogic)

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
                    <span>Send these emails from PostHog instead?</span>
                </div>
            }
            footer={
                <div className="flex flex-wrap gap-2 justify-end">
                    <LemonButton
                        type="secondary"
                        data-attr="destination-workflow-suggestion-continue"
                        onClick={continueWithDestination}
                    >
                        Continue with {template?.name ?? 'destination'}
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        data-attr="destination-workflow-suggestion-open-workflows"
                        onClick={openWorkflows}
                    >
                        See workflow templates
                    </LemonButton>
                </div>
            }
        >
            {template ? (
                <div className="flex flex-col gap-2">
                    <p className="m-0">
                        PostHog Workflows sends email from your PostHog events and person properties. You don't have to
                        stream everything to {template.name} first and build the campaigns there.
                    </p>
                    <p className="m-0 text-secondary">
                        Add delays, branches and conditions in one place, or start from a template such as a welcome
                        email sequence.
                    </p>
                </div>
            ) : null}
        </LemonModal>
    )
}
