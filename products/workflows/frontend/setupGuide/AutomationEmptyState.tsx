import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconBolt } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { onboardingWizardUrl } from './wizard/onboardingWizardSteps'
import { workflowsSetupGuideLogic } from './workflowsSetupGuideLogic'

/** The Automations list tab with no automations: a way back into the guided automation setup. */
export function AutomationEmptyState(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { browseTemplates } = useActions(workflowsSetupGuideLogic)
    const wizardEnabled = !!featureFlags[FEATURE_FLAGS.WORKFLOWS_ONBOARDING_WIZARD]

    // pinned: analytics event name - renaming breaks dashboards
    const capture = (action: 'guided-setup' | 'browse-templates'): void => {
        posthog.capture('workflows automation empty state clicked', { action })
    }

    return (
        <div className="flex flex-col items-center gap-3 py-8 text-center" data-attr="workflows-automation-empty-state">
            <div className="flex items-center justify-center size-12 rounded-full bg-surface-secondary">
                <IconBolt className="size-6" />
            </div>
            <div className="flex flex-col gap-1">
                <h3 className="mb-0 text-base font-semibold">No automations yet</h3>
                <p className="mb-0 max-w-md text-secondary">
                    Post to Slack, call a webhook or run an AI task when something happens in your product.
                </p>
            </div>
            <div className="flex flex-wrap justify-center gap-2">
                {wizardEnabled && (
                    <LemonButton
                        type="primary"
                        to={onboardingWizardUrl('automation')}
                        onClick={() => capture('guided-setup')}
                        data-attr="workflows-automation-empty-state-guided-setup"
                    >
                        Guided setup
                    </LemonButton>
                )}
                <LemonButton
                    type={wizardEnabled ? 'secondary' : 'primary'}
                    onClick={() => {
                        capture('browse-templates')
                        browseTemplates('automation')
                    }}
                    data-attr="workflows-automation-empty-state-templates"
                >
                    Browse templates
                </LemonButton>
            </div>
        </div>
    )
}
