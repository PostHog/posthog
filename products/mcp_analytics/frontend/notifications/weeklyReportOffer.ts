import { ApiError } from 'lib/api-error'

import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

export type WeeklyReportHiddenReason =
    | 'self-hosted'
    | 'not-enabled'
    | 'has-report'
    // The list failed or was cut short, so a duplicate cannot be ruled out.
    | 'unknown-reports'

export type WeeklyReportOffer =
    | { state: 'loading' }
    | { state: 'hidden'; reason: WeeklyReportHiddenReason }
    | { state: 'needs-ai-consent'; email: string }
    | { state: 'ready'; email: string }
    | { state: 'creating'; email: string }
    | { state: 'failed'; email: string; message: string }
    | { state: 'created'; report: SubscriptionApi }

export type ResolvedWeeklyReportOffer = Exclude<WeeklyReportOffer, { state: 'loading' }>
export type ActionableWeeklyReportOffer = Exclude<ResolvedWeeklyReportOffer, { state: 'hidden' }>

export type WeeklyReportSubmission =
    | { status: 'idle' }
    | { status: 'creating' }
    | { status: 'failed'; message: string }
    | { status: 'created'; report: SubscriptionApi }

/** Each input is `undefined` or `null` until it loads. */
export interface WeeklyReportOfferInputs {
    isCloudOrDev: boolean | undefined
    aiFlagEnabled: boolean | null
    aiConsentApproved: boolean | null
    userEmail: string | null
    reports: SubscriptionApi[] | 'loading' | 'unknown'
    submission: WeeklyReportSubmission
}

/**
 * Precedence, top wins:
 * created > creating > loading > self-hosted > not-enabled > has-report / unknown-reports
 * > needs-ai-consent > failed > ready.
 *
 * `created` holds only while the new report is still in `reports` and enabled. Once it is deleted or
 * turned off, nothing will arrive, so the offer comes back.
 *
 * `has-report` is project-wide on purpose: one enabled MCP report already gives the organization a
 * reason to return, whoever made it. A disabled report delivers nothing, so it does not count.
 *
 * The flag check comes before consent because approving consent cannot help someone the server still refuses.
 */
export function resolveWeeklyReportOffer(inputs: WeeklyReportOfferInputs): WeeklyReportOffer {
    const { isCloudOrDev, aiFlagEnabled, aiConsentApproved, userEmail, reports, submission } = inputs

    if (submission.status === 'created') {
        const created = Array.isArray(reports)
            ? reports.find((report) => report.id === submission.report.id)
            : undefined
        if (created?.enabled) {
            return { state: 'created', report: created }
        }
    }
    if (submission.status === 'creating' && userEmail) {
        return { state: 'creating', email: userEmail }
    }
    if (
        isCloudOrDev === undefined ||
        aiFlagEnabled === null ||
        aiConsentApproved === null ||
        userEmail === null ||
        reports === 'loading'
    ) {
        return { state: 'loading' }
    }
    if (!isCloudOrDev) {
        return { state: 'hidden', reason: 'self-hosted' }
    }
    if (!aiFlagEnabled) {
        return { state: 'hidden', reason: 'not-enabled' }
    }
    if (reports === 'unknown') {
        return { state: 'hidden', reason: 'unknown-reports' }
    }
    if (reports.some((report) => report.enabled)) {
        return { state: 'hidden', reason: 'has-report' }
    }
    if (!aiConsentApproved) {
        return { state: 'needs-ai-consent', email: userEmail }
    }
    if (submission.status === 'failed') {
        return { state: 'failed', email: userEmail, message: submission.message }
    }
    return { state: 'ready', email: userEmail }
}

const CREATE_FAILED_MESSAGE = "Couldn't create the report. Try again, or set it up from the Notifications tab."

export function createErrorMessage(error: unknown): string {
    return (error instanceof ApiError && error.detail) || CREATE_FAILED_MESSAGE
}

/** A 4xx means the server refused the request. Any other failure can leave a saved report behind. */
export function createMayHaveSucceeded(error: unknown): boolean {
    return !(error instanceof ApiError && error.status !== undefined && error.status >= 400 && error.status < 500)
}

export function weeklyReportOfferLabel(offer: WeeklyReportOffer): string {
    return offer.state === 'hidden' ? `hidden:${offer.reason}` : offer.state
}
