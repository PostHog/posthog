import type { SignalActorKindEnumApi, SignalReportAssigneeApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReportStatus } from '../types'
import { isReportClaimable, reportClaimRequest } from './reportClaim'

describe('report claim', () => {
    const assignee = (kind: SignalActorKindEnumApi): SignalReportAssigneeApi => ({
        claim_id: 'claim-1',
        kind,
        user: { id: 1, uuid: 'user-1', first_name: 'Bob', last_name: 'Smith', email: 'bob@example.com' },
        task_id: kind === 'task' ? 'task-1' : null,
        agent: kind === 'agent' ? 'codex' : null,
        claimed_at: '2026-10-22T10:00:00Z',
    })

    it.each([
        { case: 'unclaimed', current: null, claimable: true, takeover: false },
        { case: 'held by a person', current: assignee('user'), claimable: false, takeover: false },
        { case: 'held by an agent', current: assignee('agent'), claimable: true, takeover: true },
        { case: 'held by a task', current: assignee('task'), claimable: true, takeover: true },
    ])('claims a report $case', ({ current, claimable, takeover }) => {
        const report = { assignee: current, status: SignalReportStatus.READY }
        expect(isReportClaimable(report)).toBe(claimable)
        expect(reportClaimRequest(report, true)).toEqual({ takeover })
    })

    it('does not offer a claim on a resolved report', () => {
        expect(isReportClaimable({ assignee: null, status: SignalReportStatus.RESOLVED })).toBe(false)
    })
})
