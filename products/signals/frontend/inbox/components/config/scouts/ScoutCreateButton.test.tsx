import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { mockScoutSuggestionSet } from '../../../__mocks__/scoutConfigs'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
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
                '/api/projects/:team/signals/scout/suggestions/': mockScoutSuggestionSet(),
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
        featureFlagLogic.mount()
    })

    afterEach(cleanup)

    function setSuggestionsFlag(enabled: boolean): void {
        featureFlagLogic.actions.setFeatureFlags(enabled ? [FEATURE_FLAGS.SCOUTS_SUGGESTIONS_UI] : [], {
            [FEATURE_FLAGS.SCOUTS_SUGGESTIONS_UI]: enabled,
        })
    }

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

    // Closing the strip must not strand the picks: the header button reopens it in place of a chat.
    it('reopens the closed strip from the header without starting a task', async () => {
        setSuggestionsFlag(true)
        const logic = scoutSuggestionsLogic()
        logic.mount()
        await waitFor(() => expect(logic.values.hasBatch).toBe(true))
        const { findByText, queryByText } = render(<ScoutsRosterActions />)
        expect(queryByText('Suggest a scout')).toBeNull()

        logic.actions.hideStrip()
        fireEvent.click(await findByText('Suggest a scout'))

        expect(logic.values.stripHidden).toBe(false)
        expect(logic.values.collapsed).toBe(false)
        expect(startedChatTypes).toEqual([])
        logic.unmount()
    })

    // "Suggest a scout" only moves into the Ask menu for people on the suggestions strip. Off the
    // flag it stays a header button, which is the only way those people can ask for a pick.
    it.each([
        ['on the suggestions flag', true, 'Ask'],
        ['off the suggestions flag', false, 'Suggest a scout'],
    ])('spins only the button that started the task, %s', async (_name, suggestionsEnabled, spinningLabel) => {
        setSuggestionsFlag(suggestionsEnabled)
        const { findByText, getByText } = render(<ScoutsRosterActions />)

        if (suggestionsEnabled) {
            fireEvent.click(getByText('Ask'))
            fireEvent.click(await findByText('Suggest a scout'))
        } else {
            fireEvent.click(getByText('Suggest a scout'))
        }

        // Both assertions read the same render, before the task resolves and clears the state.
        expect(getByText(spinningLabel).closest('button')?.querySelector('.Spinner')).toBeTruthy()
        expect(getByText('Create scout').closest('button')?.querySelector('.Spinner')).toBeNull()
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
