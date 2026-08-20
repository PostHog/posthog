import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ScoutCreateButton } from './ScoutCreateButton'
import { ScoutsRosterActions } from './ScoutsRosterActions'
import { ScoutSuggestButton } from './ScoutSuggestButton'

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    getAccessControlDisabledReason: jest.fn(() => null),
}))

jest.mock('./ScoutCreateModal', () => ({
    ScoutCreateModal: ({ initialValues }: { initialValues?: { name?: string } }) => (
        <div>
            Manual scout form
            {initialValues?.name ? <span>{initialValues.name}</span> : null}
        </div>
    ),
}))

const mockGetAccessControlDisabledReason = getAccessControlDisabledReason as jest.MockedFunction<
    typeof getAccessControlDisabledReason
>

describe('scout creation buttons', () => {
    let startedChatTypes: string[]

    beforeEach(() => {
        startedChatTypes = []
        mockGetAccessControlDisabledReason.mockReturnValue(null)
        useMocks({
            get: {
                '/api/projects/:team/signals/scout/configs/': [],
                '/api/projects/:team/signals/scout/metadata/current/': {
                    enrolled: true,
                    banner_message: null,
                    limits: {
                        max_runs_per_tick: 1,
                        max_runs_per_day: null,
                        runs_today: 0,
                        runs_remaining_today: null,
                    },
                },
            },
            post: {
                '/api/projects/:team/signals/scout/chat_tasks/': async ({ request }) => {
                    const body = (await request.json()) as { chat_type: string }
                    startedChatTypes.push(body.chat_type)
                    return [201, { task_id: 'task-1' }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    it('opens a prefilled form without starting a task', async () => {
        const { findByText, getByText } = render(
            <ScoutCreateButton initialValues={{ name: 'signals-scout-daily-digest' }} />
        )

        fireEvent.click(getByText('Create scout'))

        expect(await findByText('Manual scout form')).toBeTruthy()
        expect(await findByText('signals-scout-daily-digest')).toBeTruthy()
        expect(startedChatTypes).toEqual([])
    })

    it('starts the authoring task from the suggest button', async () => {
        const { getByText, queryByText } = render(<ScoutSuggestButton />)

        fireEvent.click(getByText('Suggest a scout'))

        await waitFor(() => expect(startedChatTypes).toEqual(['author_scout']))
        expect(queryByText('Manual scout form')).toBeNull()
    })

    it('spins only the button that started the task', async () => {
        const { getByText } = render(<ScoutsRosterActions />)

        fireEvent.click(getByText('Suggest a scout'))

        // Both assertions read the same render, before the task resolves and clears the state.
        expect(getByText('Suggest a scout').closest('button')?.querySelector('.Spinner')).toBeTruthy()
        expect(getByText('Ask').closest('button')?.querySelector('.Spinner')).toBeNull()
        await waitFor(() => expect(startedChatTypes).toEqual(['author_scout']))
    })

    it.each([
        ['ScoutCreateButton', <ScoutCreateButton key="create" />, 'Create scout'],
        ['ScoutSuggestButton', <ScoutSuggestButton key="suggest" />, 'Suggest a scout'],
    ])('disables %s without skill editor access', (_name, element, label) => {
        mockGetAccessControlDisabledReason.mockReturnValue('Requires editor access')
        const { getByText } = render(element)

        const button = getByText(label).closest<HTMLButtonElement>('button')

        expect(button?.getAttribute('aria-disabled')).toBe('true')
        fireEvent.click(button!)
        expect(startedChatTypes).toEqual([])
    })
})
