import type {
    AwsTenantFindingApi,
    IspSendingHealthApi,
    TeamEmailReputationResponseApi,
    WorkflowEmailSendingRatesApi,
} from 'products/workflows/frontend/generated/api.schemas'

import {
    ExceededLevel,
    RATE_KINDS,
    RateKind,
    exceededLevel,
    isSendingStopped,
    minimumVolumeToClassify,
    rateOf,
} from '../reputationUtils'
import type { ReputationSetupTab } from './reputationActionTypes'

export interface ReputationActionInputs {
    response: TeamEmailReputationResponseApi
    tabUrl: (tab: ReputationSetupTab) => string
}

export interface Offender {
    workflow: WorkflowEmailSendingRatesApi
    sendShare: number
    eventShare: number
}

export interface WorkflowOverLine {
    workflow: WorkflowEmailSendingRatesApi
    rate: number
    level: ExceededLevel
}

export interface ProviderOverLine {
    isp: IspSendingHealthApi
    bounceRate: number
    level: ExceededLevel
}

/**
 * What every action reads to decide whether it shows. Facts that more than one action or the page
 * depends on are worked out here once, so no action has to read another action's rows.
 */
export interface ReputationActionContext extends ReputationActionInputs {
    findings: readonly AwsTenantFindingApi[]
    sendingStopped: boolean
    hasRateFinding: (kind: RateKind) => boolean
    /** The workflow a bounce or complaint finding blames, if one clearly stands out. */
    offender: (kind: RateKind) => Offender | null
    /** Active workflows with enough volume that are over the elevated line for this kind. */
    workflowsOverLine: (kind: RateKind) => readonly WorkflowOverLine[]
    /** Mailbox providers with enough volume that are over the elevated bounce line. */
    providersOverLine: readonly ProviderOverLine[]
}

// A named culprit has to account for a real part of the problem, and clearly more than its
// share of the sending. Otherwise the item names no workflow rather than blame the wrong one.
const MIN_OFFENDER_EVENT_SHARE = 0.1
const MIN_OFFENDER_OVER_SEND_SHARE = 1.25

/**
 * The active workflow with the most bounces (or complaints) beyond what the project average
 * predicts for its volume. Ranking by raw count would blame the biggest sender for its size even
 * when its rate is the project's own. Workflows under the volume floor are left out, so one bounce
 * in a handful of sends cannot take the blame. Paused workflows are left out because they have
 * their own item.
 */
function worstOffender(response: TeamEmailReputationResponseApi, kind: RateKind): Offender | null {
    const { workflows, reputation } = response
    const listedSends = workflows.reduce((total, w) => total + w.emails_sent, 0)
    const listedEvents = workflows.reduce((total, w) => total + rateOf(w, kind) * w.emails_sent, 0)
    // The project totals cover every workflow, and the list is capped, so prefer them for shares.
    const totalSends = reputation?.emails_sent ?? listedSends
    const projectRate = reputation ? rateOf(reputation, kind) : listedSends > 0 ? listedEvents / listedSends : 0
    const totalEvents = projectRate * totalSends
    if (totalSends === 0 || totalEvents === 0) {
        return null
    }

    let worst: { workflow: WorkflowEmailSendingRatesApi; excess: number } | null = null
    for (const workflow of workflows) {
        if (workflow.email_sending_paused || workflow.emails_sent < minimumVolumeToClassify(kind)) {
            continue
        }
        const excess = (rateOf(workflow, kind) - projectRate) * workflow.emails_sent
        if (excess > 0 && (!worst || excess > worst.excess)) {
            worst = { workflow, excess }
        }
    }
    if (!worst) {
        return null
    }
    const sendShare = worst.workflow.emails_sent / totalSends
    const eventShare = Math.min(1, (rateOf(worst.workflow, kind) * worst.workflow.emails_sent) / totalEvents)
    if (eventShare < MIN_OFFENDER_EVENT_SHARE || eventShare < sendShare * MIN_OFFENDER_OVER_SEND_SHARE) {
        return null
    }
    return { workflow: worst.workflow, sendShare, eventShare }
}

function workflowsOverLine(response: TeamEmailReputationResponseApi, kind: RateKind): WorkflowOverLine[] {
    return response.workflows.flatMap((workflow) => {
        const rate = rateOf(workflow, kind)
        const level = exceededLevel(rate, kind, workflow.emails_sent)
        return level && !workflow.email_sending_paused ? [{ workflow, rate, level }] : []
    })
}

function providersOverLine(response: TeamEmailReputationResponseApi): ProviderOverLine[] {
    return response.isps.flatMap((isp) => {
        if (isp.bounce_rate === null) {
            return []
        }
        const level = exceededLevel(isp.bounce_rate, 'bounce', isp.emails_sent)
        return level ? [{ isp, bounceRate: isp.bounce_rate, level }] : []
    })
}

export function buildReputationActionContext(inputs: ReputationActionInputs): ReputationActionContext {
    const { response } = inputs
    const findings = response.aws?.findings ?? []
    const findingTypes = new Set(findings.map((finding) => finding.finding_type))
    const hasRateFinding = (kind: RateKind): boolean => findingTypes.has(RATE_KINDS[kind].findingType)
    // Only a finding blames a workflow, so there is no offender to look for without one.
    const offenders: Record<RateKind, Offender | null> = {
        bounce: hasRateFinding('bounce') ? worstOffender(response, 'bounce') : null,
        complaint: hasRateFinding('complaint') ? worstOffender(response, 'complaint') : null,
    }
    const overLine: Record<RateKind, WorkflowOverLine[]> = {
        bounce: workflowsOverLine(response, 'bounce'),
        complaint: workflowsOverLine(response, 'complaint'),
    }
    return {
        ...inputs,
        findings,
        sendingStopped: isSendingStopped(response.aws),
        hasRateFinding,
        offender: (kind) => offenders[kind],
        workflowsOverLine: (kind) => overLine[kind],
        providersOverLine: providersOverLine(response),
    }
}
