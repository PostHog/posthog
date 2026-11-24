import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { RunLinkTagHint } from './RunLinkTagHint'

describe('<RunLinkTagHint />', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        { stored: undefined, text: /are connected to the sessions they start/, link: 'Turn it off in settings' },
        { stored: false, text: /aren't connected to sessions/, link: 'Turn it on in settings' },
    ])('stored $stored says "$link" and opens the setting in a new tab', ({ stored, text, link }) => {
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            workflows_config: {
                capture_workflows_engagement_events: true,
                ...(stored === undefined ? {} : { email_workflow_run_link_tag_enabled: stored }),
            },
        })

        render(<RunLinkTagHint />)

        expect(screen.getByText(text)).toBeInTheDocument()
        const anchor = screen.getByText(link).closest('a')
        expect(anchor).toHaveAttribute(
            'href',
            `/project/${MOCK_DEFAULT_TEAM.id}/settings/environment-workflows#workflows-email-run-link-tag`
        )
        expect(anchor).toHaveAttribute('target', '_blank')
    })
})
