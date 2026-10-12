import { WORKFLOW_BRIEF_HANDOFF_PARAM, consumeWorkflowDraftBrief } from 'lib/utils/workflowDraftHandoff'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { acceptSuggestion } from './acceptSuggestion'
import { SUGGESTION_FRAMES } from './turnSuggestionFixtures'
import { parseTurnSuggestionParams } from './turnSuggestions'

const PROJECT_ID = 997
const ENVIRONMENT_TEAM_ID = 1001
const BRIEF = 'Draft a disabled signed_up workflow with a two-day delay.'

describe('accepting a workflow suggestion', () => {
    beforeEach(() => {
        initKeaTests()
        sessionStorage.clear()
    })

    async function acceptWorkflow(): Promise<Awaited<ReturnType<typeof acceptSuggestion>>> {
        return await acceptSuggestion({
            suggestion: parseTurnSuggestionParams(SUGGESTION_FRAMES.workflow)!,
            sessionId: 'original-chat-task',
            projectId: PROJECT_ID,
            teamId: ENVIRONMENT_TEAM_ID,
            userId: undefined,
            slackIntegrationId: null,
            slackChannel: null,
            cadence: 'weekly',
            scoutBody: '',
            direction: 'decrease',
            changePercent: 20,
            notebookTitle: '',
            conversationBlocks: { blocks: [], messageCount: 0, queryCount: 0 },
            workflowPrompt: BRIEF,
        })
    }

    it('hands the edited brief once to the builder entry it opens, without putting it in the URL', async () => {
        const outcome = await acceptWorkflow()

        const url = new URL(outcome.accepted.url, 'http://localhost')
        expect(url.pathname).toBe(urls.workflowNew())
        expect(url.searchParams.get('mode')).toBe('ai')
        expect(outcome.accepted.url).not.toContain('signed_up')
        const handoffId = url.searchParams.get(WORKFLOW_BRIEF_HANDOFF_PARAM)
        const eventProperties = {
            source: 'ai_turn_suggestion',
            task_id: 'original-chat-task',
            turn_index: 0,
            team_id: String(ENVIRONMENT_TEAM_ID),
        }
        expect(outcome.eventProperties).toEqual(eventProperties)
        expect(consumeWorkflowDraftBrief(PROJECT_ID + 1, handoffId)).toBeNull()
        expect(consumeWorkflowDraftBrief(PROJECT_ID, handoffId)).toEqual({ prompt: BRIEF, eventProperties })
        expect(consumeWorkflowDraftBrief(PROJECT_ID, handoffId)).toBeNull()
    })

    it.each([
        { name: 'an entry that names no handoff', handoffId: undefined },
        { name: 'an entry that names a different handoff', handoffId: 'another-accept' },
    ])('discards the brief for $name', async ({ handoffId }) => {
        const outcome = await acceptWorkflow()

        expect(consumeWorkflowDraftBrief(PROJECT_ID, handoffId)).toBeNull()
        const acceptedHandoffId = new URL(outcome.accepted.url, 'http://localhost').searchParams.get(
            WORKFLOW_BRIEF_HANDOFF_PARAM
        )
        expect(consumeWorkflowDraftBrief(PROJECT_ID, acceptedHandoffId)).toBeNull()
    })
})
