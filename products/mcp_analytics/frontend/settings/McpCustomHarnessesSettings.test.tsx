import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { MCPCustomHarnessApi } from '../generated/api.schemas'
import { McpCustomHarnessesSettings } from './McpCustomHarnessesSettings'

const HARNESSES_URL = '/api/projects/:team_id/mcp_analytics/custom_harnesses/'

describe('McpCustomHarnessesSettings', () => {
    let stored: MCPCustomHarnessApi[]

    beforeEach(() => {
        stored = []
        useMocks({
            get: { [HARNESSES_URL]: () => [200, stored] },
            post: {
                [HARNESSES_URL]: async ({ request }) => {
                    const body = (await request.json()) as { name: string; match_pattern: string }
                    const created = {
                        ...body,
                        id: 'new',
                        created_at: '2026-01-01T00:00:00Z',
                        updated_at: '2026-01-01T00:00:00Z',
                    }
                    stored = [...stored, created]
                    return [201, created]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('adds a harness from the form and lists it', async () => {
        render(
            <Provider>
                <McpCustomHarnessesSettings />
            </Provider>
        )
        await screen.findByText('No custom harnesses yet. Add one to name calls from your own clients.')

        await userEvent.type(screen.getByPlaceholderText('Acme agent'), 'Beta bot')
        await userEvent.type(screen.getByPlaceholderText('acme-agent'), 'beta-bot')
        await userEvent.click(screen.getByText('Add harness'))

        expect(await screen.findByText('beta-bot')).toBeInTheDocument()
        expect(screen.getByText('Beta bot')).toBeInTheDocument()
        await waitFor(() => expect(screen.getByPlaceholderText('Acme agent')).toHaveValue(''))
    })
})
