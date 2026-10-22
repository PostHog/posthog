import type { SignalReportClaimApi, _UserApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReport, SignalReportStatus } from '../types'

/** Statuses the claim endpoint accepts. Mirrors the server's `CLAIMABLE_REPORT_STATUSES`. */
const CLAIMABLE_STATUSES: ReadonlySet<SignalReportStatus> = new Set([
    SignalReportStatus.READY,
    SignalReportStatus.PENDING_INPUT,
    SignalReportStatus.POTENTIAL,
    SignalReportStatus.CANDIDATE,
    SignalReportStatus.IN_PROGRESS,
    SignalReportStatus.FAILED,
])

export function reportClaimant(report: Pick<SignalReport, 'assignee'>): _UserApi | null {
    const assignee = report.assignee
    return assignee?.kind === 'user' ? assignee.user : null
}

export function isReportClaimable(report: Pick<SignalReport, 'assignee' | 'status'>): boolean {
    return CLAIMABLE_STATUSES.has(report.status) && reportClaimant(report) === null
}

// A person takes over an agent or task claim, because the agent keeps working either way.
export function reportClaimRequest(report: Pick<SignalReport, 'assignee'>, claimed: boolean): SignalReportClaimApi {
    if (!claimed) {
        return { release: true }
    }
    const assignee = report.assignee
    return { takeover: !!assignee && assignee.kind !== 'user' }
}
