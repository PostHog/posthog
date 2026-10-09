import { consumeWorkflowDraftBrief } from 'lib/utils/workflowDraftHandoff'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { NEW_WORKFLOW_HANDOFF } from 'products/workflows/frontend/Workflows/newWorkflowHandoff'

import { acceptSuggestion } from './acceptSuggestion'
import { SUGGESTION_FRAMES } from './turnSuggestionFixtures'
import { parseTurnSuggestionParams } from './turnSuggestions'

describe('accepting a workflow suggestion', () => {
    beforeEach(() => {
        initKeaTests()
        sessionStorage.clear()
    })

    it('hands the edited brief to this project once without putting it in the URL', async () => {
        const suggestion = parseTurnSuggestionParams(SUGGESTION_FRAMES.workflow)!
        const projectId = projectLogic.values.currentProjectId!
        const outcome = await acceptSuggestion({
            suggestion,
            projectId,
            userId: undefined,
            slackIntegrationId: null,
            slackChannel: null,
            cadence: 'weekly',
            scoutBody: '',
            direction: 'decrease',
            changePercent: 20,
            notebookTitle: '',
            conversationBlocks: { blocks: [], messageCount: 0, queryCount: 0 },
            workflowPrompt: 'Draft a disabled signed_up workflow with a two-day delay.',
        })

        expect(outcome.accepted.url).toBe(`${urls.workflowNew()}?mode=ai`)
        expect(consumeWorkflowDraftBrief(projectId + 1)).toBeNull()
        expect(NEW_WORKFLOW_HANDOFF.getInitialPrompt?.()).toBe(
            'Draft a disabled signed_up workflow with a two-day delay.'
        )
        expect(NEW_WORKFLOW_HANDOFF.getInitialPrompt?.()).toBeNull()
    })
})
