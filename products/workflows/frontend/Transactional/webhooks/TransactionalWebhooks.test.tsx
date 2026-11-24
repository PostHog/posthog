import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TransactionalWebhooks } from './TransactionalWebhooks'

describe('TransactionalWebhooks', () => {
    let storedConfig: Record<string, any>

    beforeEach(() => {
        storedConfig = {
            ...MOCK_DEFAULT_TEAM.workflows_config,
            capture_workflows_engagement_events: false,
            email_tracking_consent_mode: 'opt_out',
        }
        useMocks({
            get: {
                '/api/environments/:team_id/hog_functions/': { count: 0, next: null, results: [] },
            },
            patch: {
                '/api/environments/:team_id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    Object.assign(storedConfig, body.workflows_config)
                    return [200, { ...MOCK_DEFAULT_TEAM, workflows_config: { ...storedConfig } }]
                },
            },
        })
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            workflows_config: { capture_workflows_engagement_events: false, email_tracking_consent_mode: 'opt_in' },
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('turns on engagement events from the banner without undoing a setting saved in another tab', async () => {
        render(<TransactionalWebhooks />)

        expect(screen.getByText(/which are off for this project/)).toBeInTheDocument()
        expect(screen.getByText('Add webhook').closest('button')).toHaveAttribute('aria-disabled', 'true')

        fireEvent.click(screen.getByText('Turn on engagement events'))

        await waitFor(() => expect(screen.queryByText(/which are off for this project/)).not.toBeInTheDocument())
        expect(storedConfig).toMatchObject({
            capture_workflows_engagement_events: true,
            email_tracking_consent_mode: 'opt_out',
        })
        expect(screen.getByText('Add webhook').closest('button')).not.toHaveAttribute('aria-disabled', 'true')
    })
})
