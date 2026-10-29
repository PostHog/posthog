import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HarnessLogo } from './harness'

const ICON = 'data:image/png;base64,iVBORw0KGgo='

describe('HarnessLogo', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/mcp_analytics/custom_harnesses/': () => [
                    200,
                    [
                        {
                            id: '0193f2a1-0000-7000-8000-000000000001',
                            name: 'Acme agent',
                            match_pattern: 'acme-agent',
                            icon: ICON,
                            created_at: '2026-01-01T00:00:00Z',
                            updated_at: '2026-01-01T00:00:00Z',
                        },
                    ],
                ],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        ['a custom harness with an icon shows that icon', 'Acme agent', ICON],
        ['a custom harness without an icon keeps the generic mark', 'Support bot', null],
        ['a built-in harness keeps its brand mark', 'Claude Code', null],
    ])('%s', async (_, harness, expectedSrc) => {
        render(
            <Provider>
                <HarnessLogo category={harness} label={harness} />
            </Provider>
        )
        if (expectedSrc) {
            await waitFor(() => expect(screen.getByAltText(harness)).toHaveAttribute('src', expectedSrc))
        } else {
            expect(screen.getByLabelText(harness).tagName.toLowerCase()).not.toBe('img')
        }
    })
})
