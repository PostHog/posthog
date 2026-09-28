import type {
    AwsTenantFindingApi,
    AwsTenantReputationApi,
    EmailSendingRatesApi,
    IspSendingHealthApi,
    WorkflowEmailSendingRatesApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { RATE_KINDS, RateKind, RateLevel, classifyRate, minimumVolumeToClassify } from '../reputationUtils'
import type { ReputationSetupTab } from './reputationActionTypes'

export type ExceededLevel = Exclude<RateLevel, 'healthy'>

export interface ReputationActionInputs {
    aws: AwsTenantReputationApi | null
    rates: EmailSendingRatesApi | null
    /** The unsearched workflow rows, so a table search never changes what the list asks for. */
    workflows: readonly WorkflowEmailSendingRatesApi[]
    isps: readonly IspSendingHealthApi[]
    sharedDomains: readonly string[]
    suspended: boolean
    tabUrl: (tab: ReputationSetupTab) => string
}

export interface Offender {
    workflow: WorkflowEmailSendingRatesApi
    sendShare: number
    eventShare: number
}

/**
 * What every action reads to decide whether it shows. Facts that more than one action depends on
 * are worked out here once, so no action has to read another action's rows.
 */
export interface ReputationActionContext extends ReputationActionInputs {
    findings: readonly AwsTenantFindingApi[]
    hasRateFinding: (kind: RateKind) => boolean
    offender: (kind: RateKind) => Offender | null
    /** Active workflows with enough volume that are over the elevated line for this kind. */
    workflowsOverLine: (kind: RateKind) => readonly WorkflowOverLine[]
}

export interface WorkflowOverLine {
    workflow: WorkflowEmailSendingRatesApi
    rate: number
    level: ExceededLevel
}

export function rateOf(rates: { bounce_rate: number; complaint_rate: number }, kind: RateKind): number {
    return kind === 'bounce' ? rates.bounce_rate : rates.complaint_rate
}

/** The line a rate is over, or null when it is healthy or has too little volume to judge. */
export function exceededLevel(rate: number, kind: RateKind, volume: number): ExceededLevel | null {
    if (volume < minimumVolumeToClassify(kind)) {
        return null
    }
    const level = classifyRate(rate, kind)
    return level === 'healthy' ? null : level
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
function worstOffender(inputs: ReputationActionInputs, kind: RateKind): Offender | null {
    const listedSends = inputs.workflows.reduce((total, w) => total + w.emails_sent, 0)
    const listedEvents = inputs.workflows.reduce((total, w) => total + rateOf(w, kind) * w.emails_sent, 0)
    // The project totals cover every workflow, and the list is capped, so prefer them for shares.
    const totalSends = inputs.rates?.emails_sent ?? listedSends
    const projectRate = inputs.rates ? rateOf(inputs.rates, kind) : listedSends > 0 ? listedEvents / listedSends : 0
    const totalEvents = projectRate * totalSends
    if (totalSends === 0 || totalEvents === 0) {
        return null
    }

    let worst: { workflow: WorkflowEmailSendingRatesApi; excess: number } | null = null
    for (const workflow of inputs.workflows) {
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

function workflowsOverLine(inputs: ReputationActionInputs, kind: RateKind): WorkflowOverLine[] {
    return inputs.workflows.flatMap((workflow) => {
        const rate = rateOf(workflow, kind)
        const level = exceededLevel(rate, kind, workflow.emails_sent)
        return level && !workflow.email_sending_paused ? [{ workflow, rate, level }] : []
    })
}

export function buildReputationActionContext(inputs: ReputationActionInputs): ReputationActionContext {
    const findings = inputs.aws?.findings ?? []
    const findingTypes = new Set(findings.map((finding) => finding.finding_type))
    const hasRateFinding = (kind: RateKind): boolean => findingTypes.has(RATE_KINDS[kind].findingType)
    // Only a finding blames a workflow, so there is no offender to look for without one.
    const offenders: Record<RateKind, Offender | null> = {
        bounce: hasRateFinding('bounce') ? worstOffender(inputs, 'bounce') : null,
        complaint: hasRateFinding('complaint') ? worstOffender(inputs, 'complaint') : null,
    }
    const overLine: Record<RateKind, WorkflowOverLine[]> = {
        bounce: workflowsOverLine(inputs, 'bounce'),
        complaint: workflowsOverLine(inputs, 'complaint'),
    }
    return {
        ...inputs,
        findings,
        hasRateFinding,
        offender: (kind) => offenders[kind],
        workflowsOverLine: (kind) => overLine[kind],
    }
}
