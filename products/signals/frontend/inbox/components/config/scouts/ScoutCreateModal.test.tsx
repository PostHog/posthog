import { cleanup, render } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SKILL_NAME_MAX_LENGTH } from 'products/skills/frontend/skillConstants'

import { ScoutCreateModal } from './ScoutCreateModal'

describe('ScoutCreateModal', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': () => [200, { results: [] }],
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

        expect(await findByText('Slack destination')).toBeTruthy()
        expect(await findByText('Connect a Slack workspace')).toBeTruthy()
        expect(await findByText('Tags')).toBeTruthy()
    })

    it('renders the name prefix outside the field and previews the full skill name', async () => {
        const { baseElement, findByText } = render(
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

        expect(await findByText('signals-scout-')).toBeTruthy()
        expect(await findByText('signals-scout-ai-observability-daily-digest')).toBeTruthy()

        const nameInput = baseElement.querySelector<HTMLInputElement>('[data-attr="scout-create-name"]')
        expect(nameInput?.value).toBe('ai-observability-daily-digest')
        // The browser truncates a paste before onChange strips the prefix, so a cap of
        // SKILL_NAME_MAX_LENGTH - prefix would silently shorten a pasted full name.
        expect(nameInput?.getAttribute('maxlength')).toBe(String(SKILL_NAME_MAX_LENGTH))
    })
})
