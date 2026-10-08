import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ScoutCreateModal } from './ScoutCreateModal'
import { ScoutNewButton } from './ScoutNewButton'

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    getAccessControlDisabledReason: jest.fn(() => null),
}))

describe('ScoutCreateModal', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': () => [200, { results: [] }],
                '/api/projects/:team/signals/scout/configs/': [],
                '/api/projects/:team/signals/scout/metadata/current/': { enrolled: true },
            },
        })
    })

    afterEach(cleanup)

    it('includes tags and a Slack destination in the create form', async () => {
        const { findByText } = render(
            <ScoutCreateModal
                isOpen
                onClose={jest.fn()}
                initialValues={{
                    name: 'signals-scout-ai-observability-daily-digest',
                    description: 'Creates a daily AI observability digest.',
                    body: 'Review AI observability and create one actionable digest.',
                }}
            />
        )

        expect(await findByText('Tags')).toBeTruthy()

        // The destination section is collapsed, so its body only proves the section is wired up
        // once the header opens it.
        fireEvent.click(await findByText('Slack destination'))
        expect(await findByText('Connect a Slack workspace')).toBeTruthy()
    })

    it('keeps the form draft across a round trip through the chat', async () => {
        const { container, getByText } = render(<ScoutNewButton layout="buttons" surface="fleet_list" />)
        // A closing modal stays in the DOM for its close animation, so wait until only the open one matches.
        const field = (dataAttr: string): Promise<HTMLInputElement | HTMLTextAreaElement> =>
            waitFor(() => {
                const matches = container.ownerDocument.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(
                    `[data-attr="${dataAttr}"]`
                )
                expect(matches).toHaveLength(1)
                return matches[0]
            })

        fireEvent.click(getByText('Fill in the form'))
        fireEvent.change(await field('scout-create-name'), { target: { value: 'Checkout failures' } })
        fireEvent.change(await field('scout-create-description'), { target: { value: 'Checkout errors' } })
        fireEvent.change(await field('scout-create-instructions'), { target: { value: 'Report new checkout errors.' } })

        fireEvent.click(getByText('Chat with an agent instead'))
        fireEvent.change(await field('scout-chat-prompt'), { target: { value: 'Checkout errors in production' } })
        fireEvent.click(getByText('Use the form instead'))

        expect((await field('scout-create-name')).value).toBe('Checkout failures')
        expect((await field('scout-create-instructions')).value).toBe('Report new checkout errors.')
        expect((await field('scout-create-description')).value).toBe('Checkout errors in production')
    })
})
