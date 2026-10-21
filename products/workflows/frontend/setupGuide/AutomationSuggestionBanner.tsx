import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { onboardingWizardUrl } from './wizard/onboardingWizardSteps'
import { workflowsSetupGuideLogic } from './workflowsSetupGuideLogic'

/** A one-time suggestion for people who started with messaging, so they learn that workflows also automate work. */
export function AutomationSuggestionBanner(): JSX.Element | null {
    const { showAutomationSuggestion } = useValues(workflowsSetupGuideLogic)
    const { dismissAutomationSuggestion, browseTemplates } = useActions(workflowsSetupGuideLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const wizardEnabled = !!featureFlags[FEATURE_FLAGS.WORKFLOWS_ONBOARDING_WIZARD]

    if (!showAutomationSuggestion) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            className="mt-4"
            onClose={dismissAutomationSuggestion}
            action={
                wizardEnabled
                    ? {
                          children: 'Set up an automation',
                          to: onboardingWizardUrl('automation'),
                          'data-attr': 'workflows-automation-suggestion',
                      }
                    : {
                          children: 'See automation templates',
                          onClick: () => browseTemplates('automation'),
                          'data-attr': 'workflows-automation-suggestion',
                      }
            }
        >
            You can also automate other work, for example a Slack alert when a large company signs up.
        </LemonBanner>
    )
}
