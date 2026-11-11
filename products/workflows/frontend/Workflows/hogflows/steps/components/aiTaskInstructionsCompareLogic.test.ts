import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlowAction } from '../../types'
import { aiTaskInstructionsCompareLogic } from './aiTaskInstructionsCompareLogic'

const LIST_URL = '/api/environments/:team_id/hog_flows/:id/revisions/'
const REVISION_URL = '/api/environments/:team_id/hog_flows/:id/revisions/:version/'

const revisionList = (versions: number[]): Record<string, unknown> => ({
    count: versions.length,
    next: null,
    previous: null,
    results: versions.map((version) => ({ version, created_at: '2026-09-01T10:00:00Z', created_by: null })),
})

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
        ['null when the stored step has no config', [{ id: 'triage', type: 'function', name: 'Step triage' }], null],
    ])('selecting a past version yields %s', async (_, actions, expected) => {
        useMocks({ get: { [REVISION_URL]: { version: 2, created_at: '', created_by: null, content: { actions } } } })
        initKeaTests()
        const logic = aiTaskInstructionsCompareLogic({ workflowId: 'wf-1', actionId: 'triage' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.selectVersion(2)).toDispatchActions(['loadRevisionSuccess'])

        expect(logic.values.selectedRevisionPrompt).toEqual(expected)
    })

    it('reloads the version list on every open, so a version published since the last open shows', async () => {
        let published: number[] = [1]
        useMocks({
            get: {
                [LIST_URL]: () => [200, revisionList(published)],
            },
        })
        initKeaTests()
        const logic = aiTaskInstructionsCompareLogic({ workflowId: 'wf-1', actionId: 'triage' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.setOpen(true)).toDispatchActions(['loadRevisionsSuccess'])
        logic.actions.setOpen(false)
        published = [2, 1]
        await expectLogic(logic, () => logic.actions.setOpen(true)).toDispatchActions(['loadRevisionsSuccess'])

        expect(logic.values.revisionOptions.map((option) => option.value)).toEqual([2, 1])
    })

    it.each([
        ['the newest version below live', [3, 2, 1], 2],
        ['live when no version is below live', [3], null],
    ])('opening with instructions that match live selects %s', async (_, versions, expected) => {
        useMocks({
            get: {
                [LIST_URL]: () => [200, revisionList(versions)],
                [REVISION_URL]: { version: 2, created_at: '', created_by: null, content: { actions: [] } },
            },
        })
        initKeaTests()
        const logic = aiTaskInstructionsCompareLogic({ workflowId: 'wf-1', actionId: 'triage' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.setOpen(true, 3)).toDispatchActions(['loadRevisionsSuccess'])

        expect(logic.values.selectedVersion).toBe(expected)
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
