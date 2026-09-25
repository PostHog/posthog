import { endWithPunctation, humanList } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type {
    AwsTenantFindingApi,
    AwsTenantReputationApi,
    EmailSendingRatesApi,
    IspSendingHealthApi,
    WorkflowEmailSendingRatesApi,
} from 'products/workflows/frontend/generated/api.schemas'

import {
    CONFIGURE_CHANNELS_DOCS_URL,
    OTHER_ISP,
    RATE_KINDS,
    RATE_THRESHOLDS,
    REPUTATION_DOCS_URL,
    RateKind,
    RateLevel,
    classifyRate,
    formatRate,
    ispDisplayName,
    minimumVolumeToClassify,
    workflowName,
} from './reputationUtils'

export type ReputationActionSeverity = 'high' | 'medium' | 'low'

// pinned: part of the data-attr on each action's buttons, which autocapture dashboards read
type ReputationActionKind =
    | 'project-suspended'
    | 'provider-status'
    | 'paused-workflow'
    | 'finding'
    | 'project-rate'
    | 'workflow-rate'
    | 'provider-rate'

interface ReputationActionLink {
    label: string
    to: string
    external?: boolean
}

export interface ReputationAction {
    key: string
    kind: ReputationActionKind
    severity: ReputationActionSeverity
    title: string
    description: string
    primary: ReputationActionLink
    secondary?: ReputationActionLink
}

export type ReputationSetupTab = 'channels' | 'opt-outs'

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

type ExceededLevel = Exclude<RateLevel, 'healthy'>

const SEVERITY_ORDER: Record<ReputationActionSeverity, number> = { high: 0, medium: 1, low: 2 }

// Within one severity, what blocks all sending comes first, then what the provider named, then
// the rates we measure. Low-impact DNS findings sit below workflows over a line because a missing
// record rarely causes the bounces or complaints those workflows already show.
const GROUP_ORDER = {
    sendingStopped: 0,
    pausedWorkflow: 1,
    highFinding: 2,
    providerVerdict: 3,
    projectRate: 4,
    workflowRate: 5,
    lowFinding: 6,
    lowDnsFinding: 7,
    providerRate: 8,
    optionalSetup: 9,
} as const

// Complaints come first: their lines are far lower than the bounce lines, and the endpoint ranks
// workflows by complaint rate for the same reason.
const KIND_ORDER: Record<RateKind, number> = { complaint: 0, bounce: 1 }
const RATE_KIND_LIST: readonly RateKind[] = ['complaint', 'bounce']
const NO_KIND_ORDER = 2

const DNS_FINDINGS = new Set<string>(['DKIM', 'DMARC', 'SPF'])

interface RankedAction extends ReputationAction {
    group: number
    rateKind?: RateKind
    magnitude: number
}

function guideLink(label = 'How to fix it'): ReputationActionLink {
    return { label, to: REPUTATION_DOCS_URL, external: true }
}

function openWorkflow(workflow: WorkflowEmailSendingRatesApi): ReputationActionLink {
    return { label: 'Open workflow', to: urls.workflow(workflow.hog_flow_id, 'workflow') }
}

function optOutsLink(inputs: ReputationActionInputs): ReputationActionLink {
    return { label: 'Opt-outs', to: inputs.tabUrl('opt-outs') }
}

function formatShare(share: number): string {
    return share < 0.01 ? 'under 1%' : `${Math.round(share * 100)}%`
}

function rateOf(rates: { bounce_rate: number; complaint_rate: number }, kind: RateKind): number {
    return kind === 'bounce' ? rates.bounce_rate : rates.complaint_rate
}

function exceededLevel(rate: number, kind: RateKind, volume: number): ExceededLevel | null {
    if (volume < minimumVolumeToClassify(kind)) {
        return null
    }
    const level = classifyRate(rate, kind)
    return level === 'healthy' ? null : level
}

function providerSays(finding: AwsTenantFindingApi): string {
    const detail = endWithPunctation(finding.description)
    return detail ? ` Your email provider reports: ${detail}` : ''
}

interface Offender {
    workflow: WorkflowEmailSendingRatesApi
    sendShare: number
    eventShare: number
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

function sendingStoppedActions(inputs: ReputationActionInputs): RankedAction[] {
    const actions: RankedAction[] = []
    if (inputs.suspended) {
        actions.push({
            key: 'project-suspended',
            kind: 'project-suspended',
            severity: 'high',
            group: GROUP_ORDER.sendingStopped,
            magnitude: 0,
            title: 'PostHog suspended email sending for this project',
            description:
                'No workflow email goes out until the suspension ends. Fix the other items here, then contact support.',
            primary: guideLink('Read the guide'),
        })
    }
    const aws = inputs.aws
    // Findings explain a bad verdict on their own. Without any, the verdict is the only signal, and
    // leaving it out would show "nothing to fix" under the sending-paused banner.
    if (aws && aws.findings.length === 0) {
        const stopped = aws.sending_status === 'DISABLED' || aws.health === 'suspended'
        if (stopped || aws.health !== 'healthy') {
            actions.push({
                key: 'provider-status',
                kind: 'provider-status',
                severity: stopped || aws.health === 'critical' ? 'high' : 'medium',
                group: stopped ? GROUP_ORDER.sendingStopped : GROUP_ORDER.providerVerdict,
                magnitude: 0,
                title: stopped
                    ? 'Your email provider paused sending for this project'
                    : 'Your email provider flagged this project',
                description: stopped
                    ? 'Lower your bounce and spam complaint rates, then contact support to get sending re-enabled.'
                    : 'It has not named a cause yet. Check your workflows for high bounce or spam complaint rates.',
                primary: guideLink(),
            })
        }
    }
    return actions
}

function pausedWorkflowAction(workflow: WorkflowEmailSendingRatesApi): RankedAction {
    const reason = workflow.email_sending_paused_reason || 'Its email is paused.'
    return {
        key: `paused:${workflow.hog_flow_id}`,
        kind: 'paused-workflow',
        severity: 'high',
        group: GROUP_ORDER.pausedWorkflow,
        magnitude: 0,
        title: `${workflowName(workflow)} is paused`,
        description: `${reason} Check where its audience comes from before you resume sending from the workflow. If you can't resume it, contact support.`,
        primary: openWorkflow(workflow),
        secondary: guideLink(),
    }
}

function findingAction(
    finding: AwsTenantFindingApi,
    offenders: Record<RateKind, Offender | null>,
    inputs: ReputationActionInputs
): RankedAction {
    const type = finding.finding_type
    const base = {
        key: `finding:${type}`,
        kind: 'finding' as const,
        severity: (finding.impact === 'HIGH' ? 'high' : 'medium') as ReputationActionSeverity,
        group: finding.impact === 'HIGH' ? GROUP_ORDER.highFinding : GROUP_ORDER.lowFinding,
        magnitude: 0,
    }

    const kind = RATE_KIND_LIST.find((k) => RATE_KINDS[k].findingType === type)
    if (kind) {
        const offender = offenders[kind]
        const share = offender
            ? `${workflowName(offender.workflow)} sends ${formatShare(offender.sendShare)} of your email but gets ${formatShare(offender.eventShare)} of your ${RATE_KINDS[kind].events}.`
            : ''
        return {
            ...base,
            rateKind: kind,
            title: kind === 'bounce' ? 'Too many of your emails bounce' : 'Recipients mark your email as spam',
            description:
                kind === 'bounce'
                    ? offender
                        ? `${share} Addresses that hard bounce are suppressed automatically, so new bounces come from new addresses. Check where this workflow's audience comes from.`
                        : 'Your email provider sees too many hard bounces for this project. Addresses that bounce are suppressed automatically, so check where new addresses come from, such as imported lists or sign-up forms.'
                    : offender
                      ? `${share} Send it only to people who opted in, and make unsubscribing easy.`
                      : 'Your email provider sees too many spam complaints for this project. Send only to people who opted in, and make unsubscribing easy.',
            primary: offender ? openWorkflow(offender.workflow) : guideLink(),
            secondary: offender ? (kind === 'bounce' ? guideLink() : optOutsLink(inputs)) : undefined,
        }
    }
    if (DNS_FINDINGS.has(type)) {
        return {
            ...base,
            group: finding.impact === 'HIGH' ? GROUP_ORDER.highFinding : GROUP_ORDER.lowDnsFinding,
            title: `Fix your ${type} record`,
            description: `Your sending domain is missing a valid ${type} record.${providerSays(finding)} Check the DNS records your email channel shows, then verify the domain again.`,
            primary: { label: 'Open channels', to: inputs.tabUrl('channels') },
            secondary: { label: 'Setup guide', to: CONFIGURE_CHANNELS_DOCS_URL, external: true },
        }
    }
    if (type === 'BIMI') {
        return {
            ...base,
            severity: 'low',
            group: GROUP_ORDER.optionalSetup,
            title: 'Set up BIMI to show your logo in inboxes',
            description: `BIMI is optional. It needs a DMARC policy that quarantines or rejects, a logo file, and for some mailbox providers a certificate.${providerSays(finding)}`,
            primary: guideLink('Read the guide'),
        }
    }
    const titles: Record<string, string> = {
        IP_LISTING: 'Your email is on a blocklist',
        FEEDBACK_3P: 'Mailbox providers report problems with your email',
    }
    return {
        ...base,
        title: titles[type] ?? 'Your email provider flagged a problem',
        description: `${providerSays(finding).trim() || 'Your email provider flagged a problem with email from this project.'} This usually follows high bounce or spam complaint rates, so check your workflows for those first.`,
        primary: guideLink(),
    }
}

function rateAdvice(kind: RateKind, level: ExceededLevel): string {
    const high = formatRate(RATE_THRESHOLDS[kind].high)
    const elevated = formatRate(RATE_THRESHOLDS[kind].elevated)
    if (kind === 'bounce') {
        return level === 'high'
            ? `That reaches the ${high} line, where bounces start to hurt deliverability. Check where its audience comes from, and stop sending to imported or purchased lists.`
            : `That reaches the ${elevated} warning line. Check where its audience comes from before the rate reaches ${high}.`
    }
    return level === 'high'
        ? `That reaches the ${high} line. Send it only to people who opted in, send it less often, and make unsubscribing easy.`
        : `That reaches the ${elevated} warning line. Check who it sends to and how often before the rate reaches ${high}.`
}

function workflowRateActions(
    inputs: ReputationActionInputs,
    kind: RateKind,
    skipId: string | undefined
): RankedAction[] {
    const actions: RankedAction[] = []
    for (const workflow of inputs.workflows) {
        const rate = rateOf(workflow, kind)
        const level = exceededLevel(rate, kind, workflow.emails_sent)
        if (!level || workflow.email_sending_paused || workflow.hog_flow_id === skipId) {
            continue
        }
        actions.push({
            key: `workflow-${kind}:${workflow.hog_flow_id}`,
            kind: 'workflow-rate',
            severity: level === 'high' ? 'medium' : 'low',
            group: GROUP_ORDER.workflowRate,
            rateKind: kind,
            magnitude: rate / RATE_THRESHOLDS[kind].elevated,
            title: `${workflowName(workflow)} has a ${formatRate(rate)} ${RATE_KINDS[kind].event} rate`,
            description: rateAdvice(kind, level),
            primary: openWorkflow(workflow),
            secondary: kind === 'bounce' ? guideLink() : optOutsLink(inputs),
        })
    }
    return actions
}

// Many small workflows can each sit under the volume floor while together they put the project
// over a line. Nothing else in the list would say so.
function projectRateAction(inputs: ReputationActionInputs, kind: RateKind): RankedAction | null {
    if (!inputs.rates) {
        return null
    }
    const rate = rateOf(inputs.rates, kind)
    const level = exceededLevel(rate, kind, inputs.rates.emails_sent)
    if (!level) {
        return null
    }
    return {
        key: `project-${kind}`,
        kind: 'project-rate',
        severity: level === 'high' ? 'high' : 'medium',
        group: GROUP_ORDER.projectRate,
        rateKind: kind,
        magnitude: rate / RATE_THRESHOLDS[kind].elevated,
        title: `Your project has a ${formatRate(rate)} ${RATE_KINDS[kind].event} rate`,
        description:
            kind === 'bounce'
                ? 'No single workflow stands out, so the bounces come from many smaller sends. Check where your audiences come from, and stop sending to imported or purchased lists.'
                : 'No single workflow stands out, so the complaints come from many smaller sends. Send only to people who opted in, and make unsubscribing easy.',
        primary: guideLink(),
        secondary: kind === 'complaint' ? optOutsLink(inputs) : undefined,
    }
}

function providerRateActions(inputs: ReputationActionInputs): RankedAction[] {
    const sharedNote =
        inputs.sharedDomains.length > 0
            ? ` These counts include email other projects send from ${humanList(inputs.sharedDomains)}.`
            : ''
    const actions: RankedAction[] = []
    for (const isp of inputs.isps) {
        if (isp.bounce_rate === null) {
            continue
        }
        const level = exceededLevel(isp.bounce_rate, 'bounce', isp.emails_sent)
        if (!level) {
            continue
        }
        const provider = isp.isp === OTHER_ISP ? 'other providers' : ispDisplayName(isp.isp)
        actions.push({
            key: `provider-bounce:${isp.isp}`,
            kind: 'provider-rate',
            severity: level === 'high' ? 'medium' : 'low',
            group: GROUP_ORDER.providerRate,
            rateKind: 'bounce',
            magnitude: isp.bounce_rate / RATE_THRESHOLDS.bounce.elevated,
            title: `${formatRate(isp.bounce_rate)} of email to ${provider} bounces`,
            description: `A high bounce rate at one provider can mean it rejects your email, or that many of your addresses there no longer exist. Compare its delivery rate under By mailbox provider.${sharedNote}`,
            primary: guideLink(),
        })
    }
    return actions
}

function compareActions(a: RankedAction, b: RankedAction): number {
    return (
        SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
        a.group - b.group ||
        (a.rateKind ? KIND_ORDER[a.rateKind] : NO_KIND_ORDER) - (b.rateKind ? KIND_ORDER[b.rateKind] : NO_KIND_ORDER) ||
        b.magnitude - a.magnitude
    )
}

/** Everything the Reputation tab knows, turned into a list of fixes, worst first. */
export function buildReputationActions(inputs: ReputationActionInputs): ReputationAction[] {
    const findings = inputs.aws?.findings ?? []
    const findingTypes = new Set(findings.map((f) => f.finding_type))
    const hasFinding = (kind: RateKind): boolean => findingTypes.has(RATE_KINDS[kind].findingType)
    const offenders: Record<RateKind, Offender | null> = {
        bounce: hasFinding('bounce') ? worstOffender(inputs, 'bounce') : null,
        complaint: hasFinding('complaint') ? worstOffender(inputs, 'complaint') : null,
    }

    const workflowActions = RATE_KIND_LIST.flatMap((kind) =>
        workflowRateActions(inputs, kind, offenders[kind]?.workflow.hog_flow_id)
    )
    const projectActions = RATE_KIND_LIST.flatMap((kind) => {
        const covered = hasFinding(kind) || workflowActions.some((action) => action.rateKind === kind)
        const action = covered ? null : projectRateAction(inputs, kind)
        return action ? [action] : []
    })

    const actions: RankedAction[] = [
        ...sendingStoppedActions(inputs),
        ...inputs.workflows.filter((w) => w.email_sending_paused).map(pausedWorkflowAction),
        ...findings.map((finding, index) => {
            const action = findingAction(finding, offenders, inputs)
            // A tenant can hold two findings of one type, for example DKIM on two domains.
            const isRepeat = findings.findIndex((f) => f.finding_type === finding.finding_type) !== index
            return isRepeat ? { ...action, key: `${action.key}:${index}` } : action
        }),
        ...projectActions,
        ...workflowActions,
        ...providerRateActions(inputs),
    ]
    return actions.sort(compareActions).map(({ group, rateKind, magnitude, ...action }) => action)
}
