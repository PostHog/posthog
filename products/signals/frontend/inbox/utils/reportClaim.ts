import { ApiError } from 'lib/api-error'

import { signalsReportsClaim, signalsReportsRetrieve } from 'products/signals/frontend/generated/api'
import type { SignalReportApi, SignalReportClaimApi, _UserApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReport, SignalReportStatus } from '../types'
import { withInboxWriteTimeout } from './writeTimeout'

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
    if (assignee?.kind === 'agent') {
        return assignee.responsible_user ?? assignee.user
    }
    return assignee?.kind === 'user' ? assignee.user : null
}

/** The person behind a user claim or an MCP agent claim. A task claim has none. */
export function reportClaimHolder(report: Pick<SignalReport, 'assignee'>): _UserApi | null {
    const assignee = report.assignee
    return assignee?.kind === 'user' ? assignee.user : assignee?.kind === 'agent' ? assignee.responsible_user : null
}

/** The other person who holds the claim, directly or through their agent, or null. */
export function teammateClaimHolder(
    report: Pick<SignalReport, 'assignee'>,
    currentUserUuid: string | null
): _UserApi | null {
    const holder = reportClaimHolder(report)
    return holder && holder.uuid !== currentUserUuid ? holder : null
}

export function isReportClaimable(
    report: Pick<SignalReport, 'assignee' | 'status'>,
    currentUserUuid: string | null
): boolean {
    return (
        CLAIMABLE_STATUSES.has(report.status) &&
        reportClaimant(report) === null &&
        teammateClaimHolder(report, currentUserUuid) === null
    )
}

export interface ReportClaimOptions {
    currentUserUuid: string | null
    /** The person confirmed that they take over another person's claim. */
    takeover?: boolean
}

// The user takes over a task claim or their own agent's claim without a prompt, because the agent keeps working
// either way. Another person's claim needs their confirmation, and the server notifies that person.
export function reportClaimRequest(
    report: Pick<SignalReport, 'assignee'>,
    claimed: boolean,
    { currentUserUuid, takeover = false }: ReportClaimOptions
): SignalReportClaimApi {
    if (!claimed) {
        return { release: true }
    }
    const assignee = report.assignee
    const needsConfirmation = assignee?.kind === 'user' || teammateClaimHolder(report, currentUserUuid) !== null
    if (!assignee || (needsConfirmation && !takeover)) {
        return { takeover: false }
    }
    // Naming the expected claim makes the server refuse the takeover when someone else claimed meanwhile.
    return assignee.claim_id ? { takeover: true, takeover_claim_id: assignee.claim_id } : { takeover: true }
}

type FreshClaimAttempt = { fresh: SignalReportApi | null; updated: SignalReportApi | null }

/** Claims again from the server's current record. The page can still show the list's copy, whose claim may be out of date. */
async function claimFromFreshReport(
    teamId: string,
    reportId: string,
    currentUserUuid: string | null
): Promise<FreshClaimAttempt> {
    let fresh: SignalReportApi
    try {
        fresh = await withInboxWriteTimeout('claim', (options) => signalsReportsRetrieve(teamId, reportId, options))
    } catch {
        return { fresh: null, updated: null }
    }
    if (!isReportClaimable({ status: fresh.status as SignalReportStatus, assignee: fresh.assignee }, currentUserUuid)) {
        return { fresh, updated: null }
    }
    try {
        const request = reportClaimRequest(fresh, true, { currentUserUuid })
        return {
            fresh,
            updated: await withInboxWriteTimeout('claim', (options) =>
                signalsReportsClaim(teamId, reportId, request, options)
            ),
        }
    } catch {
        return { fresh, updated: null }
    }
}

/** How a claim or release ended. On failure, `message` says why, and `conflict` is true when the report changed on the server. */
export type ReportClaimOutcome =
    | { ok: true; updated: SignalReportApi }
    | { ok: false; conflict: boolean; message: string }

/**
 * Claims or releases a report for the signed-in user. Every surface that claims goes through here, so they all
 * retry an out-of-date claim the same way and give the same reason when it fails.
 */
export async function requestReportClaim(
    teamId: string,
    report: Pick<SignalReport, 'id' | 'assignee'>,
    claimed: boolean,
    options: ReportClaimOptions
): Promise<ReportClaimOutcome> {
    try {
        const request = reportClaimRequest(report, claimed, options)
        return {
            ok: true,
            updated: await withInboxWriteTimeout('claim', (requestOptions) =>
                signalsReportsClaim(teamId, report.id, request, requestOptions)
            ),
        }
    } catch (error) {
        const conflict = error instanceof ApiError && error.status === 409
        // A confirmed takeover does not retry: the claim may now belong to a person the user did not confirm.
        const retry =
            conflict && claimed && !options.takeover
                ? await claimFromFreshReport(teamId, report.id, options.currentUserUuid)
                : null
        if (retry?.updated) {
            return { ok: true, updated: retry.updated }
        }
        const message = !conflict
            ? "Couldn't update who's working on this report. Try again."
            : !options.takeover &&
                (!retry || (retry.fresh && teammateClaimHolder(retry.fresh, options.currentUserUuid)))
              ? 'Someone else is already working on this report.'
              : 'This report changed. Check it and try again.'
        return { ok: false, conflict, message }
    }
}
