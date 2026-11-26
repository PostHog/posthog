import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { SendFromCodeSnippet } from './SendFromCodeSnippet'

// The localStorage key lib/utils/oauthClient reads its OAuth session from.
const OAUTH_SESSION_KEY = 'ph_oauth_session'

describe('SendFromCodeSnippet', () => {
    afterEach(() => {
        cleanup()
        window.localStorage.removeItem(OAUTH_SESSION_KEY)
    })

    it.each([
        ['to the remote US region in OAuth mode', 'https://us.posthog.com', 'https://us.i.posthog.com'],
        ['to the remote EU region in OAuth mode', 'https://eu.posthog.com', 'https://eu.i.posthog.com'],
        ['to this app without an OAuth session', null, 'http://localhost'],
    ])('sends %s', (_case, backendHost, sdkHost) => {
        if (backendHost) {
            window.localStorage.setItem(
                OAUTH_SESSION_KEY,
                JSON.stringify({
                    backendHost,
                    clientId: 'client',
                    accessToken: 'oauth-token',
                    refreshToken: 'refresh',
                    expiresAt: 9999999999999,
                })
            )
        }
        initKeaTests()
        const { container } = render(
            <Provider>
                <SendFromCodeSnippet from={null} surface="transactional" />
            </Provider>
        )
        const snippet = container.querySelector('[data-attr=send-from-code-snippet]')!

        expect(snippet).toHaveTextContent(`host: "${sdkHost}"`)

        fireEvent.click(screen.getByText('cURL'))

        expect(snippet).toHaveTextContent(`curl -X POST ${backendHost ?? 'http://localhost'}/api/projects/`)
    })
})
