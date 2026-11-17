import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

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

    it.each([
        { stored: undefined, text: /also get ph_workflow_run/, link: 'Turn it off in settings' },
        { stored: false, text: /don't get ph_workflow_run/, link: 'Turn it on in settings' },
    ])('stored $stored says "$link" and links to the setting', ({ stored, text, link }) => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            workflows_config: {
                capture_workflows_engagement_events: true,
                ...(stored === undefined ? {} : { email_workflow_run_link_tag_enabled: stored }),
            },
        })

        render(<RunLinkTagHint />)

        expect(screen.getByText(text)).toBeInTheDocument()
        expect(screen.getByText(link).closest('a')).toHaveAttribute(
            'href',
            expect.stringMatching(/\/settings\/environment-workflows#workflows-email-run-link-tag$/)
        )
    })
    it.each([
        { opened: 'a click', open: (link: HTMLElement) => fireEvent.click(link) },
        { opened: 'a Cmd-click', open: (link: HTMLElement) => fireEvent.click(link, { metaKey: true }) },
        {
            opened: 'a middle-click',
            open: (link: HTMLElement) => fireEvent(link, new MouseEvent('auxclick', { bubbles: true, button: 1 })),
        },
    ])('shows the new setting after returning from settings opened with $opened', async ({ open }) => {
        useMocks({
            get: {
                '/api/projects/:id/': {
                    ...MOCK_DEFAULT_TEAM,
                    workflows_config: { email_workflow_run_link_tag_enabled: false },
                },
            },
        })
        render(<RunLinkTagHint />)

        open(screen.getByText('Turn it off in settings'))
        await act(async () => {
            window.dispatchEvent(new Event('focus'))
        })

        expect(await screen.findByText(/don't get ph_workflow_run/)).toBeInTheDocument()
    })
})
