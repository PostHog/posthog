import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { workflowsSetupGuideLogic } from './workflowsSetupGuideLogic'

/** A one-time suggestion for people who started with messaging, so they learn that workflows also automate work. */
export function AutomationSuggestionBanner(): JSX.Element | null {
    const { showAutomationSuggestion } = useValues(workflowsSetupGuideLogic)
    const { dismissAutomationSuggestion, browseTemplates } = useActions(workflowsSetupGuideLogic)

    if (!showAutomationSuggestion) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            className="mt-4"
            onClose={dismissAutomationSuggestion}
            action={{
                children: 'See automation templates',
                onClick: () => browseTemplates('automation'),
                'data-attr': 'workflows-automation-suggestion',
            }}
        >
            You can also automate other work, for example a Slack alert when a large company signs up.
        </LemonBanner>
    )
}
