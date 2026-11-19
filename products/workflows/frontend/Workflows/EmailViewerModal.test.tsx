import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EmailViewerModal } from './EmailViewerModal'

describe('EmailViewerModal', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/workflow_email_log/:id/': [404, { detail: 'Not found.' }],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_EMAIL_ACTIVITY], {
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_ACTIVITY]: true,
        })
    })

    afterEach(() => cleanup())

    it('keeps the rendered email loaded when switching to activity and back', async () => {
        render(
            <Provider>
                <EmailViewerModal
                    workflowId="flow-1"
                    invocationId="run-1"
                    actionId="welcome"
                    isOpen
                    onClose={() => {}}
                />
            </Provider>
        )
        const email = await screen.findByTitle('Rendered email')

        const [emailTab, activityTab] = Array.from(document.querySelectorAll('[role="tab"]'))
        fireEvent.click(activityTab)
        fireEvent.click(emailTab)

        expect(screen.getByTitle('Rendered email')).toBe(email)
    })
})
