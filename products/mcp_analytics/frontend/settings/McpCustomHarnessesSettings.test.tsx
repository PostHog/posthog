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
                        id: '0193f2a1-0000-7000-8000-000000000001',
                        created_at: '2026-01-01T00:00:00Z',
                        updated_at: '2026-01-01T00:00:00Z',
                    }
                    stored = [...stored, created]
                    return [201, created]
                },
            },
            patch: {
                [`${HARNESSES_URL}:id/`]: async ({ params, request }) => {
                    const body = (await request.json()) as Partial<MCPCustomHarnessApi>
                    stored = stored.map((h) => (h.id === params.id ? { ...h, ...body } : h))
                    return [200, stored.find((h) => h.id === params.id)]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('adds a harness inline, then edits it in place', async () => {
        render(
            <Provider>
                <McpCustomHarnessesSettings />
            </Provider>
        )
        await userEvent.click(await screen.findByText('Add custom harness'))
        await userEvent.type(screen.getByPlaceholderText('Acme agent'), 'Beta bot')
        await userEvent.type(screen.getByPlaceholderText('acme-agent'), 'beta-bot')
        await userEvent.click(screen.getByText('Save'))

        expect(await screen.findByText('Beta bot')).toBeInTheDocument()
        expect(screen.queryByPlaceholderText('Acme agent')).not.toBeInTheDocument()

        await userEvent.click(screen.getByLabelText('Edit Beta bot'))
        const nameInput = screen.getByDisplayValue('Beta bot')
        await userEvent.clear(nameInput)
        await userEvent.type(nameInput, 'Beta assistant')
        await userEvent.click(screen.getByText('Save'))

        expect(await screen.findByText('Beta assistant')).toBeInTheDocument()
        await waitFor(() => expect(screen.queryByText('Beta bot')).not.toBeInTheDocument())
    })

    it.each([
        ['a valid data URI shows a preview', 'data:image/png;base64,iVBORw0KGgo=', true],
        ['a web address shows no preview, so the browser never fetches it', 'https://example.com/icon.png', false],
    ])('%s', async (_, icon, showsPreview) => {
        render(
            <Provider>
                <McpCustomHarnessesSettings />
            </Provider>
        )
        await userEvent.click(await screen.findByText('Add custom harness'))
        await userEvent.click(screen.getByPlaceholderText('data:image/png;base64,...'))
        await userEvent.paste(icon)

        expect(screen.queryByAltText('Icon preview') !== null).toBe(showsPreview)
    })

    it('blocks opening another form while a save is pending', async () => {
        stored = [
            { id: 'a', name: 'Alpha', match_pattern: 'alpha', created_at: '', updated_at: '' },
            { id: 'b', name: 'Beta', match_pattern: 'beta', created_at: '', updated_at: '' },
        ] as MCPCustomHarnessApi[]
        let finishSave: () => void = () => {}
        useMocks({
            patch: {
                [`${HARNESSES_URL}:id/`]: () =>
                    new Promise((resolve) => {
                        finishSave = () => resolve([200, stored[0]])
                    }),
            },
        })
        render(
            <Provider>
                <McpCustomHarnessesSettings />
            </Provider>
        )
        await userEvent.click(await screen.findByLabelText('Edit Alpha'))
        await userEvent.click(screen.getByText('Save'))

        await waitFor(() => expect(screen.getByLabelText('Edit Beta')).toHaveAttribute('aria-disabled', 'true'))
        expect(screen.getByText('Add custom harness').closest('button')).toHaveAttribute('aria-disabled', 'true')
        expect(screen.getByText('Cancel').closest('button')).toHaveAttribute('aria-disabled', 'true')

        finishSave()
        await waitFor(() => expect(screen.getByLabelText('Edit Beta')).toHaveAttribute('aria-disabled', 'false'))
    })
})
