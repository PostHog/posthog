import { useActions, useValues } from 'kea'

import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { SuggestionCard } from 'scenes/max/components/SuggestionCard'

import { MAX_COMPOSER_PROMPT_LENGTH } from '../Workflows/newWorkflowComposerPrompt'
import { destinationCrossSellLogic } from './destinationCrossSellLogic'

const PROMPT_PLACEHOLDER =
    'Example: When a user signs up, send a welcome email. If they do not create a project within 3 days, send a reminder.'

/** Offers Workflows in place of a competing destination: first the choice, then a described workflow for PostHog AI. */
export function DestinationCrossSellModal(): JSX.Element {
    const { isOpen, step, prompt, target, suggestions } = useValues(destinationCrossSellLogic)
    const { closeModal, continueWithDestination, tryWorkflows, setStep, setPrompt, selectSuggestion, submitPrompt } =
        useActions(destinationCrossSellLogic)

    const templateName = target?.template.name ?? 'this destination'
    const describing = step === 'describe'
    const trimmedPrompt = prompt.trim()

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            width={560}
            hasUnsavedInput={describing && trimmedPrompt.length > 0}
            data-attr="destination-cross-sell-modal"
            title={describing ? 'Describe your workflow' : 'Message your users from PostHog instead?'}
            description={describing ? 'PostHog AI drafts the workflow. You review it before anything runs.' : undefined}
            footer={
                describing ? (
                    <>
                        <div className="flex-1">
                            <LemonButton
                                type="tertiary"
                                onClick={() => setStep('intro')}
                                data-attr="destination-cross-sell-back"
                            >
                                Back
                            </LemonButton>
                        </div>
                        <LemonButton
                            type="primary"
                            onClick={submitPrompt}
                            disabledReason={trimmedPrompt ? undefined : 'Describe the workflow first'}
                            data-attr="destination-cross-sell-create-with-ai"
                        >
                            Create workflow with AI
                        </LemonButton>
                    </>
                ) : (
                    <>
                        <LemonButton
                            type="secondary"
                            onClick={continueWithDestination}
                            data-attr="destination-cross-sell-continue-destination"
                        >
                            {`Continue with ${templateName}`}
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={tryWorkflows}
                            data-attr="destination-cross-sell-try-workflows"
                        >
                            Try workflows
                        </LemonButton>
                    </>
                )
            }
        >
            {describing ? (
                <div className="flex flex-col gap-3">
                    <LemonTextArea
                        value={prompt}
                        onChange={setPrompt}
                        placeholder={PROMPT_PLACEHOLDER}
                        minRows={4}
                        maxLength={MAX_COMPOSER_PROMPT_LENGTH}
                        autoFocus
                        data-attr="destination-cross-sell-prompt"
                    />
                    <div className="flex flex-col gap-1">
                        <span className="text-xs text-secondary">Or start from an example</span>
                        {suggestions.map((suggestion, index) => (
                            <SuggestionCard
                                key={suggestion.title}
                                title={suggestion.title}
                                description={suggestion.description}
                                onClick={() => selectSuggestion(suggestion, index)}
                                data-attr="destination-cross-sell-suggestion"
                            />
                        ))}
                    </div>
                </div>
            ) : (
                <div className="flex flex-col gap-3">
                    <p className="mb-0">
                        <span>{templateName}</span> sends your PostHog data to another tool so you can message your
                        users. PostHog workflows can do this here.
                    </p>
                    <ul className="list-disc pl-5 flex flex-col gap-1 mb-0">
                        <li>Trigger on events or cohorts</li>
                        <li>Add delays, conditions and branches</li>
                        <li>Send emails, Slack messages, SMS or webhooks</li>
                        <li>Keep your data in PostHog</li>
                    </ul>
                </div>
            )}
        </LemonModal>
    )
}
