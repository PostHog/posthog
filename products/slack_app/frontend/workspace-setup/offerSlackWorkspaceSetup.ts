import { router } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { slackAppWorkspaceSetupRetrieve } from '../generated/api'

/**
 * Offers the web setup after a Slack install that started outside the Slack landing page, for
 * example from a channel picker. The person is in the middle of another task, so this is a toast
 * and not a redirect. Nothing shows when the install has no open setup step.
 */
export async function offerSlackWorkspaceSetup(teamId: number, integrationId: number, surface: string): Promise<void> {
    let stepCount: number
    try {
        const setup = await slackAppWorkspaceSetupRetrieve(String(teamId), String(integrationId))
        stepCount = setup.steps.length
    } catch {
        return
    }
    if (stepCount === 0) {
        return
    }
    // pinned: analytics event and property names, renaming breaks dashboards
    posthog.capture('slack app workspace setup offered', { integration_id: integrationId, surface })
    lemonToast.info('Slack is connected. Finish the Slack setup, so PostHog can answer your team in Slack.', {
        autoClose: false,
        button: {
            label: 'Finish setup',
            dataAttr: 'slack-app-workspace-setup-offer',
            action: () => router.actions.push(urls.slackAppWorkspaceSetup(integrationId)),
        },
    })
}
