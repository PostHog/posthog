import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { WorkflowsEmailTrackingConsentSettings } from './WorkflowsEmailTrackingConsentSettings'
import { WorkflowsEngagementEventsSettings } from './WorkflowsEngagementEventsSettings'

describe('workflows settings save', () => {
    let storedConfig: Record<string, any>
    let saves: number

    beforeEach(() => {
        // Another tab saved both settings after this tab loaded the team.
        storedConfig = { capture_workflows_engagement_events: true, email_tracking_consent_mode: 'opt_in' }
        saves = 0
        useMocks({
            patch: {
                '/api/environments/:team_id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    Object.assign(storedConfig, body.workflows_config)
                    saves += 1
                    return [200, { ...MOCK_DEFAULT_TEAM, workflows_config: { ...storedConfig } }]
                },
            },
        })
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            workflows_config: { capture_workflows_engagement_events: false, email_tracking_consent_mode: 'off' },
        })
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            setting: 'the consent mode',
            Component: WorkflowsEmailTrackingConsentSettings,
            control: 'Opt-out',
            expected: { capture_workflows_engagement_events: true, email_tracking_consent_mode: 'opt_out' },
        },
        {
            setting: 'engagement events',
            Component: WorkflowsEngagementEventsSettings,
            control: 'Capture email engagement events',
            expected: { capture_workflows_engagement_events: true, email_tracking_consent_mode: 'opt_in' },
        },
    ])('saving $setting keeps the other setting another tab saved', async ({ Component, control, expected }) => {
        render(<Component />)

        fireEvent.click(screen.getByText(control))

        await waitFor(() => expect(saves).toBe(1))
        expect(storedConfig).toEqual(expected)
    })
})
