import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { PersonEmailsTab } from './PersonEmailsTab'

const SEND_FLAGS = [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_TIMELINE, FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API]

describe('PersonEmailsTab', () => {
    let releaseLookup = (): void => {}

    afterEach(() => {
        releaseLookup()
        cleanup()
    })

    it('opens another email while a send lookup still waits', async () => {
        const lookup = new Promise<void>((resolve) => {
            releaseLookup = resolve
        })
        const sentAt = dayjs().subtract(1, 'day').toISOString()
        useMocks({
            get: {
                '/api/projects/:team_id/persons/:id/emails/': [
                    {
                        invocation_id: '0195f3a8-1c2d-7e4f-8a9b-0c1d2e3f4a5b',
                        action_id: 'transactional_email',
                        function_id: 'flow-1',
                        subject: 'Your receipt',
                        recipient: 'ada@example.com',
                        sent_at: sentAt,
                    },
                    {
                        invocation_id: 'invocation-2',
                        action_id: 'action_email_1',
                        function_id: 'flow-2',
                        subject: 'Welcome to the team',
                        recipient: 'grace@example.com',
                        sent_at: sentAt,
                    },
                ],
                '/api/projects/:team_id/transactional_email_log/:id/': async () => {
                    await lookup
                    return [200, {}]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(SEND_FLAGS, Object.fromEntries(SEND_FLAGS.map((flag) => [flag, true])))
        render(
            <Provider>
                <PersonEmailsTab teamId={997} personId="person-1" />
            </Provider>
        )

        fireEvent.click(await screen.findByText('Your receipt'))
        fireEvent.click(screen.getByText('Welcome to the team'))

        expect(await screen.findByText('Sent to grace@example.com')).toBeTruthy()
    })
})
