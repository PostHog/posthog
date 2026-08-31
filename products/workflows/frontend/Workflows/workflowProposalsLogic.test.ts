import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowLogic } from './workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'

jest.mock('lib/lemon-ui/LemonDialog', () => ({ LemonDialog: { open: jest.fn() } }))

// Approve opens a confirm dialog, so the test has to click its primary button to get any further.
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
    let approveStatus: number
    let proposalsListStatus: number

    const proposal = {
        id: PROPOSAL_ID,
        title: 'Shorten the subject line',
        rationale: 'Open rate is under target.',
        content: { actions: [] },
        evidence: { metric: 'email open rate', current_value: 0.11, target_value: 0.2, window: '-7d' },
        base_version: 3,
        is_stale: false,
        status: 'suggested',
        created_via: 'mcp',
        source_type: 'scout',
        source_id: 'run:1:finding:subject',
        created_by: null,
        created_at: '2026-05-01T00:00:00.000Z',
        resolved_at: null,
        resolved_by: null,
        resolution_note: '',
        applied_version: null,
    }

    beforeEach(() => {
        approveBodies = []
        approveStatus = 200
        proposalsListStatus = 200
        ;(LemonDialog.open as jest.Mock).mockClear()
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': {
                    id: WORKFLOW_ID,
                    name: 'Test',
                    version: 3,
                    status: 'active',
                    actions: [],
                    edges: [],
                    draft: { actions: [] },
                    draft_updated_at: DRAFT_STAMP,
                    updated_at: '2026-05-01T00:00:00.000Z',
                },
                '/api/projects/:team_id/hog_flows/:id/proposals/': () =>
                    proposalsListStatus === 200
                        ? [200, { count: 1, results: [proposal] }]
                        : [proposalsListStatus, { detail: 'nope' }],
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
            post: {
                '/api/projects/:team_id/hog_flows/:id/proposals/:proposal_id/approve/': async ({ request }) => {
                    approveBodies.push((await request.json()) as Record<string, any>)
                    return [approveStatus, approveStatus === 200 ? proposal : { code: 'stale_update' }]
                },
                '/api/projects/:team_id/hog_flows/:id/proposals/:proposal_id/reject/': {
                    ...proposal,
                    status: 'rejected',
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

    // A failed reload (approve/reject re-dispatches loadProposals) must not blank the queue the
    // person is reading. Only the flag-off 404 is an empty queue; a 5xx keeps the last list.
    it('keeps the pending queue and reports failure when a reload hits a server error', async () => {
        await expectLogic(logic).toDispatchActions(['loadProposalsSuccess'])
        expect(logic.values.pendingProposals.map((p) => p.id)).toEqual([PROPOSAL_ID])

        proposalsListStatus = 500
        await expectLogic(logic, () => {
            logic.actions.loadProposals()
        }).toDispatchActions(['loadProposalsFailure'])

        expect(logic.values.pendingProposals.map((p) => p.id)).toEqual([PROPOSAL_ID])
    })

    it('treats the flag-off 404 as an empty queue with no failure', async () => {
        await expectLogic(logic).toDispatchActions(['loadProposalsSuccess'])

        proposalsListStatus = 404
        await expectLogic(logic, () => {
            logic.actions.loadProposals()
        }).toDispatchActions(['loadProposalsSuccess'])

        expect(logic.values.pendingProposals).toEqual([])
    })

    // The fence is the whole point: approve must carry the draft stamp the human confirmed against,
    // so a draft staged in another tab meanwhile is rejected by the server instead of overwritten.
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
        logic.actions.confirmRejectProposal(PROPOSAL_ID)
        await expectLogic(logic).toFinishAllListeners()

        expect(approveBodies).toEqual([])
    })
})
