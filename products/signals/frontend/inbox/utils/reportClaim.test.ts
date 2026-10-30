import type { SignalActorKindEnumApi, SignalReportAssigneeApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReportStatus } from '../types'
import { isReportClaimable, reportClaimant, reportClaimRequest } from './reportClaim'

describe('report claim', () => {
    const me = 'user-1'
    const assignee = (kind: SignalActorKindEnumApi, holderUuid: string = me): SignalReportAssigneeApi => {
        const person = { id: 1, uuid: holderUuid, first_name: 'Bob', last_name: 'Smith', email: 'bob@example.com' }
        return {
            claim_id: 'claim-1',
            kind,
            user: person,
            task_id: kind === 'task' ? 'task-1' : null,
            agent: kind === 'agent' ? 'codex' : null,
            claimed_at: '2026-10-22T10:00:00Z',
            responsible_user: person,
        }
    }
    const takeover = { takeover: true, takeover_claim_id: 'claim-1' }

    it.each([
        {
            case: 'unclaimed',
            current: null,
            claimable: true,
            claimant: null,
            request: { takeover: false },
            confirmed: { takeover: false },
        },
        {
            case: 'held by the user',
            current: assignee('user'),
            claimable: false,
            claimant: assignee('user').user,
            request: { takeover: false },
            confirmed: takeover,
        },
        {
            case: "held by the user's agent",
            current: assignee('agent'),
            claimable: false,
            claimant: assignee('agent').responsible_user,
            request: takeover,
            confirmed: takeover,
        },
        {
            case: 'held by an agent without a responsible user',
            current: { ...assignee('agent'), responsible_user: null },
            claimable: false,
            claimant: assignee('agent').user,
            request: takeover,
            confirmed: takeover,
        },
        {
            case: 'held by a task',
            current: assignee('task', 'user-2'),
            claimable: true,
            claimant: null,
            request: takeover,
            confirmed: takeover,
        },
        {
            case: 'held by a teammate',
            current: assignee('user', 'user-2'),
            claimable: false,
            claimant: assignee('user', 'user-2').user,
            request: { takeover: false },
            confirmed: takeover,
        },
        {
            case: "held by a teammate's agent",
            current: assignee('agent', 'user-2'),
            claimable: false,
            claimant: assignee('agent', 'user-2').responsible_user,
            request: { takeover: false },
            confirmed: takeover,
        },
    ])('claims a report $case', ({ current, claimable, claimant, request, confirmed }) => {
        const report = { assignee: current, status: SignalReportStatus.READY }
        expect(isReportClaimable(report, me)).toBe(claimable)
        expect(reportClaimant(report)).toEqual(claimant)
        expect(reportClaimRequest(report, true, { currentUserUuid: me })).toEqual(request)
        expect(reportClaimRequest(report, true, { currentUserUuid: me, takeover: true })).toEqual(confirmed)
    })

    it.each([
        { status: SignalReportStatus.FAILED, claimable: true },
        { status: SignalReportStatus.RESOLVED, claimable: false },
    ])('offers a claim on a $status report: $claimable', ({ status, claimable }) => {
        expect(isReportClaimable({ assignee: null, status }, me)).toBe(claimable)
    })
})
