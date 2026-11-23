import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { RunLinkTagHint } from './RunLinkTagHint'

describe('<RunLinkTagHint />', () => {
    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    const loadTeam = (stored: boolean | undefined): void => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            workflows_config: {
                capture_workflows_engagement_events: true,
                ...(stored === undefined ? {} : { email_workflow_run_link_tag_enabled: stored }),
            },
        })
    }

    it.each([undefined, true])('shows nothing while the project setting is %s', (stored) => {
        loadTeam(stored)

        const { container } = render(<RunLinkTagHint />)

        expect(container).toBeEmptyDOMElement()
    })

    it('links to the setting while the project setting is off', () => {
        loadTeam(false)

        render(<RunLinkTagHint />)

        expect(screen.getByText('Turn it on in settings').closest('a')).toHaveAttribute(
            'href',
            expect.stringMatching(/\/settings\/environment-workflows#workflows-email-run-link-tag$/)
        )
    })

    it('picks up the setting turned on in another tab when the editor regains focus', async () => {
        loadTeam(false)
        useMocks({
            get: {
                '/api/projects/:id/': {
                    ...MOCK_DEFAULT_TEAM,
                    workflows_config: {
                        capture_workflows_engagement_events: true,
                        email_workflow_run_link_tag_enabled: true,
                    },
                },
            },
        })
        const { container } = render(<RunLinkTagHint />)
        expect(screen.getByText('Turn it on in settings')).toBeInTheDocument()

        fireEvent.focus(window)

        await waitFor(() => expect(container).toBeEmptyDOMElement())
    })
})
