import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'

import { hogFlowsCreate, workflowDataSuggestionsBuild, workflowDataSuggestionsCurrent } from '../../generated/api'
import { SuggestionCard } from './suggestionCards'
import { workflowDataSuggestionsLogic } from './workflowDataSuggestionsLogic'

jest.mock('../../generated/api', () => ({
    hogFlowsCreate: jest.fn(),
    workflowDataSuggestionsBuild: jest.fn(),
    workflowDataSuggestionsCurrent: jest.fn(),
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
        jest.mocked(workflowDataSuggestionsCurrent).mockResolvedValue({ status: 'ready', suggestions: [] })
        initKeaTests()
    })

    it('opens the saved draft after a successful build', async () => {
        jest.mocked(workflowDataSuggestionsBuild).mockResolvedValue({
            workflow: { name: 'Welcome new users' },
            uses_saved_template: false,
        })
        jest.mocked(hogFlowsCreate).mockResolvedValue({ id: 'workflow-1' } as any)
        const logic = workflowDataSuggestionsLogic({ surface: 'empty_state' })
        logic.mount()

        await logic.asyncActions.startSuggestion(card)

        expect(hogFlowsCreate).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ name: 'Welcome new users', status: 'draft' })
        )
        expect(router.values.location.pathname).toContain('workflow-1')
        expect(logic.values.buildingKey).toBeNull()
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
