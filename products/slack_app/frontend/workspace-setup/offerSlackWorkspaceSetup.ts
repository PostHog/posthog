import { router } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { slackAppWorkspaceSetupRetrieve } from '../generated/api'

/** A toast and not a redirect, because the person is in the middle of another task, such as picking a channel. */
export async function offerSlackWorkspaceSetup(teamId: number, integrationId: number, surface: string): Promise<void> {
    const setup = await slackAppWorkspaceSetupRetrieve(String(teamId), String(integrationId))
    if (setup.steps.length === 0) {
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
