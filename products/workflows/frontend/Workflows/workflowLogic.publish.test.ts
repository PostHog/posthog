import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow, HogFlowAction } from './hogflows/types'
import { openPublishConfirmDialog } from './PublishImpactDialog'
import { AiTaskPromptChange, getAiTaskPromptChanges, workflowLogic } from './workflowLogic'

jest.mock('./PublishImpactDialog', () => ({ openPublishConfirmDialog: jest.fn() }))

const WORKFLOW_ID = 'wf-publish-1'
const DRAFT_AT = '2026-05-01T00:00:00.000000Z'
const NEWER_DRAFT_AT = '2026-05-01T00:05:00.000000Z'
const OLDER_DRAFT_AT = '2026-04-30T23:55:00.000000Z'

const functionStep = (id: string, prompt: string, templateId = 'template-posthog-create-task'): HogFlowAction => ({
    id,
    type: 'function',
    name: `Step ${id}`,
    description: '',
    created_at: 0,
    updated_at: 0,
    config: { template_id: templateId, inputs: { prompt: { value: prompt } } },
})

const makeWorkflow = (live: HogFlowAction[], staged: HogFlowAction[]): HogFlow =>
    ({
        id: WORKFLOW_ID,
        name: 'Publish test',
        actions: live,
        edges: [],
        status: 'active',
        draft: { actions: staged },
    }) as unknown as HogFlow

describe('workflowLogic publish', () => {
    describe('getAiTaskPromptChanges', () => {
        test.each<[string, HogFlowAction[], HogFlowAction[], AiTaskPromptChange[]]>([
            [
                'returns live and staged instructions for a changed AI task step',
                [functionStep('a', 'Triage the ticket')],
                [functionStep('a', 'Triage the ticket and tag it')],
                [
                    {
                        actionId: 'a',
                        stepName: 'Step a',
                        livePrompt: 'Triage the ticket',
                        stagedPrompt: 'Triage the ticket and tag it',
                    },
                ],
            ],
            [
                'skips an AI task step with unchanged instructions',
                [functionStep('a', 'Same')],
                [functionStep('a', 'Same')],
                [],
            ],
            [
                'compares an AI task step the draft adds against empty instructions',
                [],
                [functionStep('a', 'New step')],
                [{ actionId: 'a', stepName: 'Step a', livePrompt: '', stagedPrompt: 'New step' }],
            ],
            [
                'treats a step stored without inputs as having empty instructions',
                [
                    {
                        ...functionStep('a', ''),
                        config: { template_id: 'template-posthog-create-task' },
                    } as HogFlowAction,
                ],
                [functionStep('a', 'Triage the ticket')],
                [{ actionId: 'a', stepName: 'Step a', livePrompt: '', stagedPrompt: 'Triage the ticket' }],
            ],
            [
                'compares a step the draft turns into an AI task against empty instructions',
                [functionStep('a', 'Old', 'template-webhook')],
                [functionStep('a', 'New')],
                [{ actionId: 'a', stepName: 'Step a', livePrompt: '', stagedPrompt: 'New' }],
            ],
            [
                'skips a change to line endings only',
                [functionStep('a', 'One\r\nTwo')],
                [functionStep('a', 'One\nTwo')],
                [],
            ],
            [
                'compares a step the draft turns into another kind of step against empty instructions',
                [functionStep('a', 'Old')],
                [functionStep('a', 'Webhook body', 'template-webhook')],
                [{ actionId: 'a', stepName: 'Step a', livePrompt: 'Old', stagedPrompt: '' }],
            ],
            [
                'skips a function step from another template',
                [functionStep('a', 'Old', 'template-webhook')],
                [functionStep('a', 'New', 'template-webhook')],
                [],
            ],
        ])('%s', (_, live, staged, expected) => {
            expect(getAiTaskPromptChanges(makeWorkflow(live, staged))).toEqual(expected)
        })
    })

    describe('publishDraft', () => {
        let logic: ReturnType<typeof workflowLogic.build>
        let getCalls: number
        let previewDraftAt: string
        let duringPreview: () => void

        beforeEach(async () => {
            duringPreview = () => {}
            jest.mocked(openPublishConfirmDialog).mockClear()
            getCalls = 0
            const serverWorkflow = (draftAt: string): HogFlow => ({
                ...makeWorkflow([functionStep('a', 'Old')], [functionStep('a', 'New')]),
                updated_at: draftAt,
                draft_updated_at: draftAt,
            })
            useMocks({
                get: {
                    '/api/environments/:team_id/hog_flows/:id/': () => {
                        getCalls += 1
                        return [200, serverWorkflow(DRAFT_AT)]
                    },
                    '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
                },
                patch: { '/api/environments/:team_id/hog_flows/:id/': () => [200, serverWorkflow(NEWER_DRAFT_AT)] },
                post: {
                    '/api/environments/:team_id/hog_flows/:id/publish/': () => {
                        duringPreview()
                        return [
                            200,
                            {
                                published: false,
                                in_flight_runs: 0,
                                draft_updated_at: previewDraftAt,
                                confirm_token: 'token',
                                impact: null,
                            },
                        ]
                    },
                },
            })
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
        })

        it('opens the dialog with the instruction diffs of the previewed draft', async () => {
            previewDraftAt = DRAFT_AT

            await expectLogic(logic, () => logic.actions.publishDraft()).toFinishAllListeners()

            expect(openPublishConfirmDialog).toHaveBeenCalledWith(
                expect.objectContaining({
                    aiTaskPromptChanges: [
                        { actionId: 'a', stepName: 'Step a', livePrompt: 'Old', stagedPrompt: 'New' },
                    ],
                })
            )
            expect(getCalls).toBe(1)
        })

        it.each([
            ['the editor saved after the preview read the draft', OLDER_DRAFT_AT, () => {}],
            [
                'the user edited while the preview loaded',
                DRAFT_AT,
                () => logic.actions.setWorkflowValue('name', 'Edited during the preview'),
            ],
        ])('waits instead of opening the dialog or reloading when %s', async (_, draftAt, edit) => {
            previewDraftAt = draftAt
            duringPreview = edit

            await expectLogic(logic, () => logic.actions.publishDraft()).toFinishAllListeners()

            expect(openPublishConfirmDialog).not.toHaveBeenCalled()
            expect(getCalls).toBe(1)
        })

        it('reloads instead of opening the dialog when the server holds a newer draft', async () => {
            previewDraftAt = NEWER_DRAFT_AT

            await expectLogic(logic, () => logic.actions.publishDraft()).toDispatchActions([
                'loadWorkflow',
                'loadWorkflowSuccess',
            ])

            expect(openPublishConfirmDialog).not.toHaveBeenCalled()
            expect(getCalls).toBe(2)
        })
    })
})
