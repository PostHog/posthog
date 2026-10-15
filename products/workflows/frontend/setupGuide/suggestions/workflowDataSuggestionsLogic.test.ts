import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'

import { loadEntrySource } from '../../Broadcasts/broadcastUsage'
import {
    hogFlowsCreate,
    workflowDataSuggestionsBuild,
    workflowDataSuggestionsCurrent,
    workflowDataSuggestionsGenerate,
} from '../../generated/api'
import { SuggestionCard } from './suggestionCards'
import { workflowDataSuggestionsLogic } from './workflowDataSuggestionsLogic'

jest.mock('../../generated/api', () => ({
    hogFlowsCreate: jest.fn(),
    workflowDataSuggestionsBuild: jest.fn(),
    workflowDataSuggestionsCurrent: jest.fn(),
    workflowDataSuggestionsGenerate: jest.fn(),
}))

const card: SuggestionCard = {
    key: 'ai-suggestion-1',
    stage: 'signup',
    title: 'Welcome new users',
    description: 'Send a welcome email after sign-up.',
    triggerEvent: 'user_registered',
    weeklyCount: 42,
    steps: ['email'],
    suggestionId: 'suggestion-1',
}

describe('workflowDataSuggestionsLogic', () => {
    beforeEach(() => {
        jest.mocked(workflowDataSuggestionsGenerate).mockResolvedValue({ status: 'ready', suggestions: [] })
        initKeaTests()
    })

    it('polls while the background run generates the cards', async () => {
        jest.useFakeTimers()
        try {
            jest.mocked(workflowDataSuggestionsGenerate).mockResolvedValue({ status: 'generating', suggestions: [] })
            jest.mocked(workflowDataSuggestionsCurrent).mockResolvedValue({
                status: 'ready',
                suggestions: [
                    {
                        id: 'suggestion-1',
                        name: 'Welcome new users',
                        description: 'Send a welcome email after sign-up.',
                        reason: 'user_registered fires every day.',
                        trigger_event: 'user_registered',
                        weekly_count: 42,
                        stage: 'signup',
                        step_outline: ['email'],
                    },
                ],
            })
            const logic = workflowDataSuggestionsLogic({ surface: 'empty_state' })
            logic.mount()

            await jest.advanceTimersByTimeAsync(0)
            expect(logic.values.generating).toBe(true)
            expect(workflowDataSuggestionsCurrent).not.toHaveBeenCalled()

            await jest.advanceTimersByTimeAsync(2000)

            expect(logic.values.generating).toBe(false)
            expect(logic.values.cards.map((shown) => shown.suggestionId)).toEqual(['suggestion-1'])
        } finally {
            jest.useRealTimers()
        }
    })

    it('opens the saved draft after a successful build', async () => {
        jest.mocked(workflowDataSuggestionsBuild).mockResolvedValue({
            status: 'ready',
            workflow: { name: 'Welcome new users' },
            uses_saved_template: false,
        })
        jest.mocked(hogFlowsCreate).mockResolvedValue({ id: 'workflow-1' } as any)
        const logic = workflowDataSuggestionsLogic({ surface: 'empty_state' })
        logic.mount()

        await logic.asyncActions.startSuggestion(card)

        expect(hogFlowsCreate).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ name: 'Welcome new users', status: 'draft' }),
            expect.objectContaining({ signal: expect.anything() })
        )
        expect(router.values.location.pathname).toContain('workflow-1')
        expect(loadEntrySource('workflow-1')).toBe('data_suggestion')
        expect(logic.values.buildingKey).toBeNull()
    })

    it.each([
        ['saves the draft once the background build is ready', false, 1],
        ['stops without saving when the person leaves the page', true, 0],
    ])('%s', async (_name, leaves, saves) => {
        jest.useFakeTimers()
        try {
            jest.mocked(workflowDataSuggestionsBuild)
                .mockResolvedValueOnce({ status: 'building', workflow: null, uses_saved_template: false })
                .mockResolvedValue({ status: 'ready', workflow: { name: 'Welcome' }, uses_saved_template: false })
            jest.mocked(hogFlowsCreate).mockResolvedValue({ id: 'workflow-1' } as any)
            const logic = workflowDataSuggestionsLogic({ surface: 'empty_state' })
            logic.mount()
            await jest.advanceTimersByTimeAsync(0)

            logic.actions.startSuggestion(card)
            await jest.advanceTimersByTimeAsync(0)
            if (leaves) {
                logic.unmount()
            }
            await jest.advanceTimersByTimeAsync(2000)

            expect(hogFlowsCreate).toHaveBeenCalledTimes(saves)
        } finally {
            jest.useRealTimers()
        }
    })

    it('shows the error and frees the card when the build fails', async () => {
        const toast = jest.spyOn(lemonToast, 'error')
        jest.mocked(workflowDataSuggestionsBuild).mockRejectedValue({ detail: 'This suggestion has expired.' })
        const logic = workflowDataSuggestionsLogic({ surface: 'empty_state' })
        logic.mount()

        await logic.asyncActions.startSuggestion(card)

        expect(toast).toHaveBeenCalledWith('This suggestion has expired.')
        expect(hogFlowsCreate).not.toHaveBeenCalled()
        expect(logic.values.buildingKey).toBeNull()
    })
})
