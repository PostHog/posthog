import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { mockScoutSuggestionSet } from '../../../__mocks__/scoutConfigs'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { ScoutCreateButton } from './ScoutCreateButton'
import { ScoutNewButton } from './ScoutNewButton'
import { ScoutsRosterActions } from './ScoutsRosterActions'
import { ScoutSuggestButton } from './ScoutSuggestButton'

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    getAccessControlDisabledReason: jest.fn(() => null),
}))

jest.mock('./ScoutCreateModal', () => ({
    ScoutCreateModal: ({
        initialValues,
        onSwitchToChat,
    }: {
        initialValues?: { name?: string; description?: string }
        onSwitchToChat?: (description: string) => void
    }) => (
        <div>
            Manual scout form
            {initialValues?.name ? <span>{initialValues.name}</span> : null}
            {initialValues?.description ? <span>{initialValues.description}</span> : null}
            {onSwitchToChat ? (
                <button onClick={() => onSwitchToChat(initialValues?.description ?? '')}>Back to chat</button>
            ) : null}
        </div>
    ),
}))

const mockGetAccessControlDisabledReason = getAccessControlDisabledReason as jest.MockedFunction<
    typeof getAccessControlDisabledReason
>

describe('scout creation buttons', () => {
    let startedChatTypes: string[]
    let startedUserPrompts: (string | undefined)[]
    let refreshRequests: number

    beforeEach(() => {
        startedChatTypes = []
        startedUserPrompts = []
        refreshRequests = 0
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
                    const body = (await request.json()) as { chat_type: string; user_prompt?: string }
                    startedChatTypes.push(body.chat_type)
                    startedUserPrompts.push(body.user_prompt)
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
        await waitFor(() => expect(logic.values.hasPicks).toBe(true))
        const { findByText, queryByText } = render(<ScoutsRosterActions />)
        expect(queryByText('Suggest a scout')).toBeNull()

        logic.actions.hideStrip()
        fireEvent.click(await findByText('Suggest a scout'))

        expect(logic.values.stripHidden).toBe(false)
        expect(logic.values.collapsed).toBe(false)
        expect(startedChatTypes).toEqual([])
        logic.unmount()
    })

    // Reopening is local, so it must not wait on whatever else the header is starting. A separate
    // test because the setup differs: this one needs a sibling task in flight.
    it('reopens the closed strip while another header task is starting', async () => {
        setSuggestionsFlag(true)
        const logic = scoutSuggestionsLogic()
        logic.mount()
        await waitFor(() => expect(logic.values.hasPicks).toBe(true))
        const { container, findByText, getByText } = render(<ScoutsRosterActions />)
        logic.actions.hideStrip()
        await findByText('Suggest a scout')

        fireEvent.click(getByText('Ask'))
        fireEvent.click(getByText('How is my scout troop performing?'))

        // Read before the task resolves and clears the state, the same window the spinner lives in.
        const reopen = container.querySelector<HTMLButtonElement>('[data-attr="scout-suggestions-show"]')
        expect(reopen?.getAttribute('aria-disabled')).not.toBe('true')
        expect(reopen?.querySelector('.Spinner')).toBeNull()
        fireEvent.click(reopen!)

        expect(logic.values.stripHidden).toBe(false)
        await waitFor(() => expect(startedChatTypes).toEqual(['fleet_overview']))
        logic.unmount()
    })

    // A project with no picks has no strip to reopen, so the header button is the only entry point
    // there. A headless scan would spend minutes with nothing on screen, so it opens the chat.
    it('opens the authoring chat from the header on a project with no picks', async () => {
        setSuggestionsFlag(true)
        useMocks({
            get: { '/api/projects/:team/signals/scout/suggestions/': mockScoutSuggestionSet({ items: [] }) },
            post: {
                '/api/projects/:team/signals/scout/suggestions/refresh/': () => {
                    refreshRequests += 1
                    return [200, { workflow_id: 'workflow-1' }]
                },
            },
        })
        const logic = scoutSuggestionsLogic()
        logic.mount()
        const { findByText } = render(<ScoutsRosterActions />)
        // The button is busy until the batch is known, so a press before then does nothing.
        await waitFor(() => expect(logic.values.suggestionSet).not.toBeNull())

        fireEvent.click(await findByText('Suggest a scout'))

        await waitFor(() => expect(startedChatTypes).toEqual(['author_scout']))
        expect(refreshRequests).toBe(0)
        logic.unmount()
    })

    it.each([
        ['on the suggestions flag', true],
        ['off the suggestions flag', false],
    ])('starts an authoring chat on the typed request from New scout, %s', async (_name, suggestionsEnabled) => {
        setSuggestionsFlag(suggestionsEnabled)
        const { findByText, getByText, queryByText, container } = render(<ScoutsRosterActions />)

        fireEvent.click(getByText('Ask'))
        await findByText('How is my scout troop performing?')
        expect(queryByText('Suggest a scout')).toBeNull()

        fireEvent.click(getByText('New scout'))
        fireEvent.click(await findByText('Chat with an agent'))
        const start = getByText('Start chat').closest('button')
        expect(start?.getAttribute('aria-disabled')).toBe('true')
        fireEvent.change(container.ownerDocument.querySelector('[data-attr="scout-chat-prompt"]')!, {
            target: { value: 'Watch for spam signups' },
        })
        fireEvent.click(getByText('Start chat'))

        await waitFor(() => expect(startedChatTypes).toEqual(['author_scout']))
        expect(startedUserPrompts).toEqual(['Watch for spam signups'])
    })

    it('carries the typed request between the chat and the form', async () => {
        const { findByText, getByText, container } = render(<ScoutsRosterActions />)

        fireEvent.click(getByText('New scout'))
        fireEvent.click(await findByText('Chat with an agent'))
        fireEvent.click(getByText('Churn risk'))
        fireEvent.click(getByText('Use the form instead'))

        const churnPrompt = await findByText(/usage drops sharply/)
        expect(await findByText('Manual scout form')).toBeTruthy()

        fireEvent.click(churnPrompt.parentElement!.querySelector('button')!)
        const prompt = await waitFor(() => {
            const textarea = container.ownerDocument.querySelector<HTMLTextAreaElement>(
                '[data-attr="scout-chat-prompt"]'
            )
            expect(textarea).toBeTruthy()
            return textarea!
        })
        expect(prompt.value).toContain('usage drops sharply')
        expect(startedChatTypes).toEqual([])
    })

    it.each([
        ['ScoutCreateButton', <ScoutCreateButton key="create" />, 'Create scout'],
        ['ScoutSuggestButton', <ScoutSuggestButton key="suggest" />, 'Suggest a scout'],
        ['ScoutNewButton', <ScoutNewButton key="new" surface="fleet_list" />, 'New scout'],
    ])('disables %s without skill editor access', (_name, element, label) => {
        mockGetAccessControlDisabledReason.mockReturnValue('Requires editor access')
        const { getByText } = render(element)

        const button = getByText(label).closest<HTMLButtonElement>('button')

        expect(button?.getAttribute('aria-disabled')).toBe('true')
        fireEvent.click(button!)
        expect(startedChatTypes).toEqual([])
    })
})
