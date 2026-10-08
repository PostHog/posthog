import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlowAction } from '../../types'
import { aiTaskInstructionsCompareLogic } from './aiTaskInstructionsCompareLogic'

const REVISION_URL = '/api/environments/:team_id/hog_flows/:id/revisions/:version/'

const aiTask = (id: string, prompt: string): HogFlowAction => ({
    id,
    type: 'function',
    name: `Step ${id}`,
    description: '',
    created_at: 0,
    updated_at: 0,
    config: { template_id: 'template-posthog-create-task', inputs: { prompt: { value: prompt } } },
})

describe('aiTaskInstructionsCompareLogic', () => {
    afterEach(resumeKeaLoadersErrors)

    it.each([
        ['the instructions of the step in that version', [aiTask('triage', 'Old instructions')], 'Old instructions'],
        ['null when the step is not in that version', [aiTask('other', 'Something else')], null],
    ])('selecting a past version yields %s', async (_, actions, expected) => {
        useMocks({ get: { [REVISION_URL]: { version: 2, created_at: '', created_by: null, content: { actions } } } })
        initKeaTests()
        const logic = aiTaskInstructionsCompareLogic({ workflowId: 'wf-1', actionId: 'triage' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.selectVersion(2)).toDispatchActions(['loadRevisionSuccess'])

        expect(logic.values.selectedRevisionPrompt).toEqual(expected)
    })

    it('reports a failed version load, and clears it on switching to the live version', async () => {
        useMocks({ get: { [REVISION_URL]: () => [500, { detail: 'error' }] } })
        initKeaTests()
        silenceKeaLoadersErrors()
        const logic = aiTaskInstructionsCompareLogic({ workflowId: 'wf-1', actionId: 'triage' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.selectVersion(2)).toDispatchActions(['loadRevisionFailure'])

        expect(logic.values.revisionLoadFailed).toBe(true)

        logic.actions.selectVersion(null)

        expect(logic.values.revisionLoadFailed).toBe(false)
    })
})
