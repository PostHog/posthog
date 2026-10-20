import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCheckbox, LemonModal } from '@posthog/lemon-ui'

import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'

import { destinationWorkflowSuggestionLogic } from './destinationWorkflowSuggestionLogic'

type Advantage = { title: string; detail: string }

const STOPS_ON_CONVERSION: Advantage = {
    title: 'Stop when they convert.',
    detail: 'A workflow can end as soon as someone does what you wanted, like upgrading.',
}

const EMAIL_ADVANTAGES: Advantage[] = [
    { title: 'No second copy of your data.', detail: 'Workflows use your PostHog events and person properties.' },
    STOPS_ON_CONVERSION,
    { title: 'Results in one place.', detail: 'See opens and clicks next to the rest of your PostHog data.' },
]

const CHANNEL_ADVANTAGES: Advantage[] = [
    {
        title: 'One workflow, every channel.',
        detail: 'Put this message next to an email, an SMS or a wait, in the order you want them.',
    },
    STOPS_ON_CONVERSION,
    { title: 'Results in one place.', detail: 'See what each step did next to the rest of your PostHog data.' },
]

const AI_BUILD_ADVANTAGE: Advantage = {
    title: 'Free to set up.',
    detail: 'Building these workflows with AI costs you nothing.',
}

export function DestinationWorkflowSuggestionModal(): JSX.Element {
    const { template, events, selectedEvents, buildState, canBuildWorkflows, buildUnavailable, kind } = useValues(
        destinationWorkflowSuggestionLogic
    )
    const { closeSuggestion, continueWithDestination, createWorkflows, openWorkflowEditor, toggleEvent } = useActions(
        destinationWorkflowSuggestionLogic
    )
    const building = buildState === 'building'
    const toolName = template?.name ?? 'this destination'
    const advantages =
        kind === 'channel'
            ? CHANNEL_ADVANTAGES
            : canBuildWorkflows
              ? [...EMAIL_ADVANTAGES, AI_BUILD_ADVANTAGE]
              : EMAIL_ADVANTAGES

    return (
        <LemonModal
            isOpen={!!template}
            onClose={closeSuggestion}
            width={560}
            title={
                <div className="flex gap-2 items-center">
                    {template ? (
                        <HogFunctionIcon src={template.icon_url} className={template.icon_class_name} size="small" />
                    ) : null}
                    <span>
                        {kind === 'channel'
                            ? 'Send this from a PostHog workflow?'
                            : 'Send these emails from PostHog instead?'}
                    </span>
                </div>
            }
            footer={
                <div className="flex flex-wrap gap-2 justify-end">
                    <LemonButton
                        type="secondary"
                        data-attr="destination-workflow-suggestion-continue"
                        onClick={continueWithDestination}
                        disabledReason={building ? 'Building your workflows' : undefined}
                    >
                        Continue with {toolName}
                    </LemonButton>
                    {canBuildWorkflows ? (
                        <LemonButton
                            type="primary"
                            data-attr="destination-workflow-suggestion-create-workflows"
                            onClick={createWorkflows}
                            loading={building}
                            disabledReason={selectedEvents.length === 0 ? 'Pick at least one event' : undefined}
                        >
                            {buildState === 'failed' ? 'Try again' : 'Create workflows'}
                        </LemonButton>
                    ) : (
                        <LemonButton
                            type="primary"
                            data-attr="destination-workflow-suggestion-create-workflow"
                            onClick={openWorkflowEditor}
                        >
                            Create a workflow
                        </LemonButton>
                    )}
                </div>
            }
        >
            {template ? (
                <div className="flex flex-col gap-3">
                    <p className="m-0">
                        {kind === 'channel'
                            ? `You're about to stream these events to ${toolName}. A PostHog workflow can send the same ${toolName} message as one step, so the message sits in the flow with your other channels.`
                            : canBuildWorkflows
                              ? `You're about to stream these events to ${toolName}. PostHog Workflows can send emails on them directly, and we can build those workflows for you.`
                              : `It looks like you want to stream your events to ${toolName}, maybe to send emails. PostHog Workflows can send those emails directly.`}
                    </p>
                    <ul className="m-0 pl-4 list-disc flex flex-col gap-1">
                        {advantages.map(({ title, detail }) => (
                            <li key={title}>
                                <strong>{title}</strong> {detail}
                            </li>
                        ))}
                    </ul>
                    {canBuildWorkflows ? (
                        <>
                            <div className="flex flex-col gap-1">
                                <span className="font-semibold">Build a workflow for:</span>
                                {events.map((event) => (
                                    <LemonCheckbox
                                        key={event}
                                        checked={selectedEvents.includes(event)}
                                        onChange={() => toggleEvent(event)}
                                        disabled={building}
                                        label={<code className="break-all">{event}</code>}
                                    />
                                ))}
                            </div>
                            <p className="m-0 text-secondary">
                                We save them as drafts. They stay off until you turn them on, and you need a verified
                                email domain to send.
                            </p>
                        </>
                    ) : (
                        <p className="m-0 text-secondary">
                            {kind === 'channel'
                                ? `The step sends through your own ${toolName} account, the same as here. Your workflow stays off until you turn it on.`
                                : 'You need a verified email domain to send. Your workflow stays off until you turn it on.'}
                        </p>
                    )}
                    {buildUnavailable ? (
                        <LemonBanner type="info">
                            We can't build workflows for your organization, but you can create one yourself.
                        </LemonBanner>
                    ) : null}
                    {building ? (
                        <LemonBanner type="info">Building your workflows. This can take a few minutes.</LemonBanner>
                    ) : buildState === 'failed' ? (
                        <LemonBanner type="error">
                            We couldn't build these workflows. Try again, or continue with {toolName}.
                        </LemonBanner>
                    ) : null}
                </div>
            ) : null}
        </LemonModal>
    )
}
