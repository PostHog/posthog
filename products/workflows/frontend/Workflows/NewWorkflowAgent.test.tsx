import '@testing-library/jest-dom'

import { act, cleanup, render } from '@testing-library/react'
import { router } from 'kea-router'

import { WORKFLOW_BRIEF_HANDOFF_PARAM, storeWorkflowDraftBrief } from 'lib/utils/workflowDraftHandoff'
import { MAX_SIDE_PANEL_ID } from 'scenes/max/components/PhaiSidePanelChat'
import { maxMocks } from 'scenes/max/testUtils'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { composerSeedLogic } from 'products/posthog_ai/frontend/api/logics'

import { NewWorkflowAgent } from './NewWorkflowAgent'

jest.mock('products/posthog_ai/frontend/api/runner', () => ({
    ...jest.requireActual('products/posthog_ai/frontend/api/runner'),
    SidePanelRunner: () => null,
}))

describe('NewWorkflowAgent', () => {
    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        sessionStorage.clear()
    })

    afterEach(cleanup)

    it('takes a brief handed to the composer that is already open', () => {
        router.actions.push(urls.workflowNew(), { mode: 'ai' })
        render(<NewWorkflowAgent />)
        const seed = composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID })
        expect(seed.values.seed?.prompt ?? '').toBe('')

        const handoffId = storeWorkflowDraftBrief(projectLogic.values.currentProjectId!, 'Remind new signups.', {
            source: 'ai_turn_suggestion',
            task_id: 'original-chat-task',
            turn_index: 0,
            team_id: '997',
        })
        act(() => router.actions.push(urls.workflowNew(), { mode: 'ai', [WORKFLOW_BRIEF_HANDOFF_PARAM]: handoffId }))

        expect(seed.values.seed).toEqual({ prompt: 'Remind new signups.', autoSubmit: false })
    })
})
