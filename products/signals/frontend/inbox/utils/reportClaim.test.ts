import type { SignalActorKindEnumApi, SignalReportAssigneeApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReportStatus } from '../types'
import { isReportClaimable, reportClaimant, reportClaimRequest } from './reportClaim'

describe('report claim', () => {
    const assignee = (kind: SignalActorKindEnumApi): SignalReportAssigneeApi => ({
        claim_id: 'claim-1',
        kind,
        user: { id: 1, uuid: 'user-1', first_name: 'Bob', last_name: 'Smith', email: 'bob@example.com' },
        task_id: kind === 'task' ? 'task-1' : null,
        agent: kind === 'agent' ? 'codex' : null,
        claimed_at: '2026-10-22T10:00:00Z',
        responsible_user: { id: 1, uuid: 'user-1', first_name: 'Bob', last_name: 'Smith', email: 'bob@example.com' },
    })

    it.each([
        { case: 'unclaimed', current: null, claimable: true, claimant: null, request: { takeover: false } },
        {
            case: 'held by a person',
            current: assignee('user'),
            claimable: false,
            claimant: assignee('user').user,
            request: { takeover: false },
        },
        {
            case: 'held by an agent',
            current: assignee('agent'),
            claimable: false,
            claimant: assignee('agent').responsible_user,
            request: { takeover: true, takeover_claim_id: 'claim-1' },
        },
        {
            case: 'held by an agent without a responsible user',
            current: { ...assignee('agent'), responsible_user: null },
            claimable: false,
            claimant: assignee('agent').user,
            request: { takeover: true, takeover_claim_id: 'claim-1' },
        },
        {
            case: 'held by a task',
            current: assignee('task'),
            claimable: true,
            claimant: null,
            request: { takeover: true, takeover_claim_id: 'claim-1' },
        },
    ])('claims a report $case', ({ current, claimable, claimant, request }) => {
        const report = { assignee: current, status: SignalReportStatus.READY }
        expect(isReportClaimable(report)).toBe(claimable)
        expect(reportClaimant(report)).toEqual(claimant)
        expect(reportClaimRequest(report, true)).toEqual(request)
    })

    it.each([
        { status: SignalReportStatus.FAILED, claimable: true },
        { status: SignalReportStatus.RESOLVED, claimable: false },
    ])('offers a claim on a $status report: $claimable', ({ status, claimable }) => {
        expect(isReportClaimable({ assignee: null, status })).toBe(claimable)
    })
})
