import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { initKeaTests } from '~/test/init'
import { PreflightStatus } from '~/types'

import { OAuthRedirectUri } from './OAuthRedirectUri'

describe('OAuthRedirectUri', () => {
    beforeEach(() => {
        initKeaTests(false)
        preflightLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows only the configured site URL and nothing before preflight resolves', () => {
        const { container } = render(<OAuthRedirectUri />)

        expect(container).toBeEmptyDOMElement()

        act(() => {
            preflightLogic.actions.loadPreflightSuccess({ site_url: 'https://posthog.example.com' } as PreflightStatus)
        })

        expect(screen.getByText('https://posthog.example.com/api/mcp_store/oauth_redirect/')).toBeInTheDocument()
        expect(screen.queryByText(new RegExp(window.location.origin))).not.toBeInTheDocument()
    })
})
