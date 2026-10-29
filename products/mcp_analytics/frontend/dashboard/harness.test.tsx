import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { mcpCustomHarnessesLogic } from '../settings/mcpCustomHarnessesLogic'
import { HarnessLogo } from './harness'
import { HarnessLabel } from './HarnessLabel'

const ICON = 'data:image/png;base64,iVBORw0KGgo='

describe('harness icons', () => {
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
        ['a custom harness named like an object property keeps the generic mark', 'constructor', null],
    ])('%s', async (_, harness, expectedSrc) => {
        const logic = mcpCustomHarnessesLogic()
        logic.mount()
        await waitFor(() => expect(logic.values.customHarnesses).toHaveLength(1))

        const { container } = render(
            <Provider>
                <HarnessLogo category={harness} label={harness} />
                <HarnessLabel category={harness} />
            </Provider>
        )
        const icons = Array.from(container.querySelectorAll('img')).map((img) => img.getAttribute('src'))
        expect(icons).toEqual(expectedSrc ? [expectedSrc, expectedSrc] : [])
    })
})
