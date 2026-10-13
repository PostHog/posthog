import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowLogic } from '../workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'

jest.mock('lib/lemon-ui/LemonDialog', () => ({ LemonDialog: { open: jest.fn(), openForm: jest.fn() } }))

const confirmTheDialog = (): void => {
    const call = (LemonDialog.open as jest.Mock).mock.calls.at(-1)
    call[0].primaryButton.onClick()
}

const WORKFLOW_ID = 'wf-proposals-1'
const PROPOSAL_ID = 'proposal-1'
const DRAFT_STAMP = '2026-05-02T00:00:00.000Z'

describe('workflowProposalsLogic', () => {
    let logic: ReturnType<typeof workflowProposalsLogic.build>
    let approveBodies: Record<string, any>[]
    let rejectedList: Record<string, any>[]
    let rejectBodies: Record<string, any>[]
    let approveStatus: number
    let proposalsListStatus: number
    let workflowVersion: number
    let workflowStatus: string
    let workflowDraft: Record<string, any> | null
    let workflowDraftStamp: string | null

    const proposal = {
        id: PROPOSAL_ID,
        title: 'Shorten the subject line',
        rationale: 'Open rate is under target.',
        content: { actions: [] },
        evidence: { metric: 'email open rate', current_value: 0.11, target_value: 0.2, window: '-7d' },
        base_version: 3,
        is_stale: false,
        status: 'suggested',
        source_id: 'run:1:finding:subject',
        created_at: '2026-05-01T00:00:00.000Z',
        resolved_at: null,
        resolved_by: null,
        applied_version: null,
    }

    beforeEach(() => {
        approveBodies = []
        rejectedList = []
        rejectBodies = []
        approveStatus = 200
        proposalsListStatus = 200
        workflowVersion = 3
        workflowStatus = 'active'
        workflowDraft = { actions: [] }
        workflowDraftStamp = DRAFT_STAMP
        ;(LemonDialog.open as jest.Mock).mockClear()
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => [
                    200,
                    {
                        id: WORKFLOW_ID,
                        name: 'Test',
                        version: workflowVersion,
                        status: workflowStatus,
                        actions: [],
                        edges: [],
                        draft: workflowDraft,
                        draft_updated_at: workflowDraftStamp,
                        updated_at: '2026-05-01T00:00:00.000Z',
                    },
                ],
                '/api/projects/:team_id/hog_flows/:id/proposals/': ({ request }) => {
                    if (new URL(request.url).searchParams.get('status') === 'rejected') {
                        return [200, { count: rejectedList.length, results: rejectedList }]
                    }
                    return proposalsListStatus === 200
                        ? [200, { count: 1, results: [proposal] }]
                        : [proposalsListStatus, { detail: 'nope' }]
                },
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
            post: {
                '/api/projects/:team_id/hog_flows/:id/proposals/:proposal_id/approve/': async ({ request }) => {
                    approveBodies.push((await request.json()) as Record<string, any>)
                    return [approveStatus, approveStatus === 200 ? proposal : { code: 'stale_update' }]
                },
                '/api/projects/:team_id/hog_flows/:id/proposals/:proposal_id/reject/': async ({ request }) => {
                    rejectBodies.push((await request.json()) as Record<string, any>)
                    const rejected = { ...proposal, status: 'rejected', resolved_at: '2026-05-03T00:00:00.000Z' }
                    rejectedList.push(rejected)
                    return [200, rejected]
                },
            },
        })
        initKeaTests()
        logic = workflowProposalsLogic({ id: WORKFLOW_ID })
        logic.mount()
    })

    it('loads the pending queue on mount', async () => {
        await expectLogic(logic).toDispatchActions(['loadProposalsSuccess'])
        expect(logic.values.pendingProposals.map((p) => p.id)).toEqual([PROPOSAL_ID])
    })

    it('keeps the pending queue and reports failure when a reload hits a server error', async () => {
        await expectLogic(logic).toDispatchActions(['loadProposalsSuccess'])
        expect(logic.values.pendingProposals.map((p) => p.id)).toEqual([PROPOSAL_ID])

        proposalsListStatus = 500
        await expectLogic(logic, () => {
            logic.actions.loadProposals()
        }).toDispatchActions(['loadProposalsFailure'])

        expect(logic.values.pendingProposals.map((p) => p.id)).toEqual([PROPOSAL_ID])
        // Without this the panel cannot tell a failed list from one nobody asked for, and spins forever.
        expect(logic.values.listsUnreadable).toBe(true)

        proposalsListStatus = 200
        await expectLogic(logic, () => {
            logic.actions.reloadLists()
        }).toDispatchActions(['loadProposalsSuccess'])

        expect(logic.values.listsUnreadable).toBe(false)
    })

    it('treats the flag-off 404 as an empty queue with no failure', async () => {
        await expectLogic(logic).toDispatchActions(['loadProposalsSuccess'])

        proposalsListStatus = 404
        await expectLogic(logic, () => {
            logic.actions.loadProposals()
        }).toDispatchActions(['loadProposals', 'loadProposalsSuccess'])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.pendingProposals).toEqual([])
    })

    it('reloads the queue when the workflow version moves', async () => {
        const flowLogic = workflowLogic({ id: WORKFLOW_ID })
        flowLogic.mount()
        await expectLogic(flowLogic).toDispatchActions(['loadWorkflowSuccess'])
        await expectLogic(logic).toDispatchActions(['loadProposalsSuccess'])

        logic.actions.setOutcome(PROPOSAL_ID, { versions: [] } as any)
        expect(logic.values.outcomes[PROPOSAL_ID]).not.toBeUndefined()

        workflowVersion = 4
        await expectLogic(logic, () => {
            flowLogic.actions.loadWorkflow()
        }).toDispatchActions(['clearOutcomes', 'loadProposals', 'loadApplied'])
        expect(logic.values.lastSeenVersion).toBe(4)
        expect(logic.values.outcomes).toEqual({})
    })

    it('reloads the queue when a discard rewrites the draft stamp without moving the version', async () => {
        const flowLogic = workflowLogic({ id: WORKFLOW_ID })
        flowLogic.mount()
        await expectLogic(flowLogic).toDispatchActions(['loadWorkflowSuccess'])
        await expectLogic(logic).toDispatchActions(['loadProposalsSuccess'])

        workflowDraft = null
        workflowDraftStamp = null
        await expectLogic(logic, () => {
            flowLogic.actions.loadWorkflow()
        }).toDispatchActions(['loadProposals', 'loadApplied'])
        expect(logic.values.lastSeenVersion).toBe(3)
        expect(logic.values.lastSeenDraftStamp).toBeNull()
    })

    it('approving sends the draft stamp it saw as the overwrite fence', async () => {
        const flowLogic = workflowLogic({ id: WORKFLOW_ID })
        flowLogic.mount()
        await expectLogic(flowLogic).toDispatchActions(['loadWorkflowSuccess'])

        logic.actions.approveProposal(PROPOSAL_ID)
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => {
            confirmTheDialog()
        }).toDispatchActions([flowLogic.actionTypes.loadWorkflow])

        expect(approveBodies).toEqual([{ overwrite: true, expected_draft_updated_at: DRAFT_STAMP }])
        expect(logic.values.resolvingId).toBeNull()
    })

    it('approving with nothing staged asks the server not to overwrite a draft staged since', async () => {
        const flowLogic = workflowLogic({ id: WORKFLOW_ID })
        flowLogic.mount()
        await expectLogic(flowLogic).toDispatchActions(['loadWorkflowSuccess'])

        workflowDraft = null
        workflowDraftStamp = null
        await expectLogic(flowLogic, () => {
            flowLogic.actions.loadWorkflow()
        }).toDispatchActions(['loadWorkflowSuccess'])
        ;(LemonDialog.open as jest.Mock).mockClear()

        logic.actions.approveProposal(PROPOSAL_ID)
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => {
            confirmTheDialog()
        }).toDispatchActions([flowLogic.actionTypes.loadWorkflow])

        expect(approveBodies).toEqual([{ overwrite: false, expected_draft_updated_at: null }])
    })

    it('will not stage a suggestion on a workflow with no publish or discard controls', async () => {
        const flowLogic = workflowLogic({ id: WORKFLOW_ID })
        flowLogic.mount()
        await expectLogic(flowLogic).toDispatchActions(['loadWorkflowSuccess'])

        workflowStatus = 'draft'
        await expectLogic(flowLogic, () => {
            flowLogic.actions.loadWorkflow()
        }).toDispatchActions(['loadWorkflowSuccess'])
        ;(LemonDialog.open as jest.Mock).mockClear()

        expect(logic.values.approveDisabledReason).toBe('Only a live workflow can stage a suggestion as a draft')

        logic.actions.approveProposal(PROPOSAL_ID)
        await expectLogic(logic).toFinishAllListeners()
        expect(LemonDialog.open as jest.Mock).not.toHaveBeenCalled()

        logic.actions.confirmApproveProposal(PROPOSAL_ID, null)
        await expectLogic(logic).toFinishAllListeners()
        expect(approveBodies).toEqual([])
    })

    it('a 409 reloads the workflow and the queue instead of leaving stale state on screen', async () => {
        approveStatus = 409
        const flowLogic = workflowLogic({ id: WORKFLOW_ID })
        flowLogic.mount()
        await expectLogic(flowLogic).toDispatchActions(['loadWorkflowSuccess'])

        await expectLogic(logic, () => {
            logic.actions.confirmApproveProposal(PROPOSAL_ID, DRAFT_STAMP)
        }).toDispatchActions([flowLogic.actionTypes.loadWorkflow, logic.actionTypes.loadProposals])

        expect(logic.values.resolvingId).toBeNull()
    })

    it('ignores a second resolve while one is in flight', async () => {
        await expectLogic(logic).toDispatchActions(['loadProposalsSuccess'])
        logic.actions.setResolvingId(PROPOSAL_ID)

        logic.actions.confirmApproveProposal(PROPOSAL_ID, DRAFT_STAMP)
        logic.actions.confirmRejectProposal(PROPOSAL_ID, '')
        await expectLogic(logic).toFinishAllListeners()

        expect(approveBodies).toEqual([])
        expect(rejectBodies).toEqual([])
    })

    it('rejecting sends the reason the person gave', async () => {
        await expectLogic(logic).toDispatchActions(['loadProposalsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.confirmRejectProposal(PROPOSAL_ID, '  It is the sign-off email.  ')
        }).toDispatchActions(['removeResolvedProposal'])

        expect(rejectBodies).toEqual([{ reason: 'It is the sign-off email.' }])
    })

    it('rejecting moves the suggestion into the rejected list, most recently rejected first', async () => {
        await expectLogic(logic).toDispatchActions(['loadProposalsSuccess', 'loadRejectedSuccess'])
        // Filed after the one about to be rejected, but rejected before it.
        rejectedList.push({
            ...proposal,
            id: 'rejected-earlier',
            status: 'rejected',
            resolved_at: '2026-05-01T00:00:00.000Z',
        })
        await expectLogic(logic, () => {
            logic.actions.loadRejected()
        }).toDispatchActions(['loadRejectedSuccess'])
        expect(logic.values.rejectedProposals.map((p) => p.id)).toEqual(['rejected-earlier'])

        await expectLogic(logic, () => {
            logic.actions.confirmRejectProposal(PROPOSAL_ID, '')
        }).toDispatchActions(['removeResolvedProposal', 'loadRejected', 'loadRejectedSuccess'])

        expect(logic.values.rejectedProposals.map((p) => p.id)).toEqual([PROPOSAL_ID, 'rejected-earlier'])
    })

    it('reopens the reject dialog with the reason when the request fails', async () => {
        useMocks({
            post: { '/api/projects/:team_id/hog_flows/:id/proposals/:proposal_id/reject/': () => [500, {}] },
        })
        await expectLogic(logic).toDispatchActions(['loadProposalsSuccess'])
        ;(LemonDialog.openForm as jest.Mock).mockClear()

        logic.actions.confirmRejectProposal(PROPOSAL_ID, 'It is the sign-off email.')
        await expectLogic(logic).toFinishAllListeners()

        expect((LemonDialog.openForm as jest.Mock).mock.calls.at(-1)[0].initialValues).toEqual({
            reason: 'It is the sign-off email.',
        })
    })
})
