import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

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

        const anchor = screen.getByText('Turn it on in settings').closest('a')
        expect(anchor).toHaveAttribute(
            'href',
            expect.stringMatching(/\/settings\/environment-workflows#workflows-email-run-link-tag$/)
        )
        expect(anchor).toHaveAttribute('target', '_blank')
    })
})
