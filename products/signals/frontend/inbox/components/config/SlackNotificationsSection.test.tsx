import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { IntegrationType } from '~/types'

import { SlackNotificationsSection } from './SlackNotificationsSection'

const WORKSPACE = { id: 1, kind: 'slack', display_name: 'PostHog' } as IntegrationType
const DM_TARGET = 'U0123ABC456|@sam'
const DM_SAVED = 'PostHog sends these to @sam in Slack.'
// Anchored: the team card's copy carries the same sentence, after one of its own.
const CHANNEL_HELP = /^PostHog must be in the channel/

describe('SlackNotificationsSection', () => {
    let autonomyConfig: Record<string, unknown> | null = null
    let saves: Record<string, unknown>[] = []

    beforeEach(() => {
        initKeaTests()
        autonomyConfig = null
        saves = []
        // msw handlers reset between tests, so register per test rather than once per file.
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': () => [200, { results: [WORKSPACE] }],
                '/api/environments/:team_id/integrations/:id/channels': () => [200, { channels: [], has_more: false }],
                '/api/projects/:team_id/signals/config/': () => [200, { default_slack_notification_channel: null }],
                '/api/users/@me/signal_autonomy/': () =>
                    autonomyConfig ? [200, autonomyConfig] : [404, { detail: 'Not found' }],
            },
            post: {
                '/api/users/@me/signal_autonomy/': async ({ request }) => {
                    const body = (await request.clone().json()) as Record<string, unknown>
                    saves.push(body)
                    // The client never names the direct message target; the API answers with it.
                    const { slack_notification_direct_message: wantsDm, ...fields } = body
                    autonomyConfig = {
                        ...autonomyConfig,
                        ...fields,
                        ...(wantsDm ? { slack_notification_channel: DM_TARGET } : {}),
                    }
                    return [200, autonomyConfig]
                },
            },
        })
    })
    afterEach(cleanup)

    it('opens a saved direct message on the direct message tab', async () => {
        autonomyConfig = { slack_notification_integration_id: 1, slack_notification_channel: DM_TARGET }

        render(<SlackNotificationsSection />)

        expect(await screen.findByText(DM_SAVED)).toBeInTheDocument()
        expect(screen.queryByText(CHANNEL_HELP)).not.toBeInTheDocument()
    })

    // The channel picker emits a clear when it mounts empty, which must not wipe a saved target.
    it('keeps a saved direct message when the channel tab is opened', async () => {
        autonomyConfig = { slack_notification_integration_id: 1, slack_notification_channel: DM_TARGET }

        render(<SlackNotificationsSection />)
        expect(await screen.findByText(DM_SAVED)).toBeInTheDocument()
        await userEvent.click(screen.getByText('Channel'))

        expect(await screen.findByText(CHANNEL_HELP)).toBeInTheDocument()
        await new Promise((resolve) => setTimeout(resolve, 300))
        expect(saves).toEqual([])
    })

    it('turns the card on straight into a direct message', async () => {
        render(<SlackNotificationsSection />)

        await userEvent.click(await screen.findByLabelText('Enable Slack notifications'))

        expect(await screen.findByText(DM_SAVED)).toBeInTheDocument()
        expect(saves).toEqual([{ slack_notification_integration_id: 1, slack_notification_direct_message: true }])
    })

    // Switching from a channel asks the API for the target, since only it knows the member id.
    it('replaces a saved channel with a direct message', async () => {
        autonomyConfig = { slack_notification_integration_id: 1, slack_notification_channel: 'C0123ABC456|#alerts' }

        render(<SlackNotificationsSection />)
        await userEvent.click(await screen.findByText('Direct message'))
        await userEvent.click(await screen.findByText('Send me a direct message'))

        expect(await screen.findByText(DM_SAVED)).toBeInTheDocument()
        expect(saves).toEqual([{ slack_notification_integration_id: 1, slack_notification_direct_message: true }])
    })
})
