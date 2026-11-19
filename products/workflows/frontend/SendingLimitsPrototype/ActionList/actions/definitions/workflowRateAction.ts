import {
    ExceededLevel,
    RATE_KINDS,
    RATE_KIND_LIST,
    RATE_THRESHOLDS,
    RateKind,
    formatRate,
    workflowName,
} from '../../reputationUtils'
import { defineReputationAction } from '../defineReputationAction'
import type { WorkflowOverLine } from '../reputationActionContext'
import { LOWER_RATES_DOCS, openWorkflow } from '../reputationActionCtas'

interface WorkflowRate extends WorkflowOverLine {
    kind: RateKind
}

function rateAdvice(kind: RateKind, level: ExceededLevel): string {
    const high = formatRate(RATE_THRESHOLDS[kind].high)
    const elevated = formatRate(RATE_THRESHOLDS[kind].elevated)
    if (kind === 'bounce') {
        return level === 'high'
            ? `That reaches the ${high} line, where PostHog pauses a workflow's email if its rate over a day stays this high. Check where its audience comes from, and stop sending to imported or purchased lists.`
            : `That reaches the ${elevated} warning line. PostHog pauses a workflow's email at ${high}, so check where its audience comes from now.`
    }
    return level === 'high'
        ? `That reaches the ${high} line, where PostHog pauses a workflow's email if its rate over a day stays this high. Send it only to people who opted in, send it less often, and make unsubscribing easy.`
        : `That reaches the ${elevated} warning line. PostHog pauses a workflow's email at ${high}, so check who it sends to and how often now.`
}

/**
 * A workflow over a bounce or complaint line. A workflow that a finding already blames is left
 * out, because the finding's row names it.
 */
export const workflowRateAction = defineReputationAction<WorkflowRate>({
    kind: 'workflow-rate',
    detect: (context) =>
        RATE_KIND_LIST.flatMap((kind) => {
            const blamed = context.offender(kind)?.workflow.hog_flow_id
            return context
                .workflowsOverLine(kind)
                .filter(({ workflow }) => workflow.hog_flow_id !== blamed)
                .map((overLine) => ({ ...overLine, kind }))
        }),
    content: ({ workflow, rate, level, kind }) => ({
        key: `workflow-${kind}:${workflow.hog_flow_id}`,
        rank: {
            severity: level === 'high' ? 'high' : 'medium',
            slot: 'workflowRate',
            rateKind: kind,
            magnitude: rate / RATE_THRESHOLDS[kind].elevated,
        },
        title: `${workflowName(workflow)} has a ${formatRate(rate)} ${RATE_KINDS[kind].event} rate`,
        description: rateAdvice(kind, level),
        docsLink: LOWER_RATES_DOCS,
    }),
    cta: ({ workflow }) => openWorkflow(workflow),
})
