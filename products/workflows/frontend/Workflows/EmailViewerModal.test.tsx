import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EmailViewerChip, EmailViewerModal } from './EmailViewerModal'

describe('EmailViewerModal', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/workflow_email_log/:id/': [404, { detail: 'Not found.' }],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        setActivityFlag(true)
    })

    const setActivityFlag = (enabled: boolean): void => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_EMAIL_ACTIVITY], {
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_ACTIVITY]: enabled,
        })
    }

    const selectedTab = (): string | null | undefined =>
        document.querySelector('[role="tab"][aria-selected="true"]')?.textContent

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

    it.each([
        { button: 'workflow-log-view-email', tab: 'Email' },
        { button: 'workflow-log-view-email-activity', tab: 'Activity' },
    ])('opens the viewer on the $tab tab from $button', ({ button, tab }) => {
        render(
            <Provider>
                <EmailViewerChip workflowId="flow-1" invocationId="run-1" actionId="welcome" />
            </Provider>
        )

        fireEvent.click(document.querySelector(`[data-attr="${button}"]`)!)

        expect(selectedTab()).toBe(tab)
    })

    it('shows only the view email link while the flag is off', () => {
        setActivityFlag(false)
        render(
            <Provider>
                <EmailViewerChip workflowId="flow-1" invocationId="run-1" actionId="welcome" />
            </Provider>
        )

        expect(screen.getByText('View email')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="workflow-log-view-email-activity"]')).toBeNull()
    })
})
