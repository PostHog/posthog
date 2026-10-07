import type { FindingTypeEnumApi } from 'products/workflows/frontend/generated/api.schemas'

import { RATE_KINDS, RATE_KIND_LIST, RateKind, workflowName } from '../../reputationUtils'
import { defineReputationAction } from '../defineReputationAction'
import type { Offender } from '../reputationActionContext'
import { LOWER_RATES_DOCS, VIEW_WORKFLOWS, manageOptOuts, openWorkflow } from '../reputationActionCtas'
import { IndexedFinding, findingsOfType, isHighImpact } from '../reputationFindings'

export const RATE_FINDING_TYPES: readonly FindingTypeEnumApi[] = RATE_KIND_LIST.map(
    (kind) => RATE_KINDS[kind].findingType
)

interface RateFinding extends IndexedFinding {
    kind: RateKind
    offender: Offender | null
}

function formatShare(share: number): string {
    return share < 0.01 ? 'under 1%' : `${Math.round(share * 100)}%`
}

function rateFindingDescription({ kind, offender }: RateFinding): string {
    const share = offender
        ? `${workflowName(offender.workflow)} sends ${formatShare(offender.sendShare)} of your email but gets ${formatShare(offender.eventShare)} of your ${RATE_KINDS[kind].events}.`
        : ''
    if (kind === 'bounce') {
        return offender
            ? `${share} Addresses that hard bounce are suppressed automatically, so new bounces come from new addresses. Check where this workflow's audience comes from.`
            : 'Your email provider sees too many hard bounces for this project. Addresses that bounce are suppressed automatically, so check where new addresses come from, such as imported lists or sign-up forms.'
    }
    return offender
        ? `${share} Send it only to people who opted in, and make unsubscribing easy.`
        : 'Your email provider sees too many spam complaints for this project. Send only to people who opted in, and make unsubscribing easy.'
}

/**
 * The provider sees too many bounces or spam complaints. When one workflow clearly causes them,
 * the row names it and opens it.
 */
export const rateFindingAction = defineReputationAction<RateFinding>({
    kind: 'rate-finding',
    detect: (context) =>
        RATE_KIND_LIST.flatMap((kind) =>
            findingsOfType(context.findings, [RATE_KINDS[kind].findingType]).map((indexed) => ({
                ...indexed,
                kind,
                offender: context.offender(kind),
            }))
        ),
    content: (match) => ({
        key: `finding:${match.finding.finding_type}`,
        rank: {
            severity: isHighImpact(match.finding) ? 'high' : 'medium',
            slot: isHighImpact(match.finding) ? 'highFinding' : 'lowFinding',
            rateKind: match.kind,
            order: match.index,
        },
        title: match.kind === 'bounce' ? 'Too many of your emails bounce' : 'Recipients mark your email as spam',
        description: rateFindingDescription(match),
        docsLink: LOWER_RATES_DOCS,
    }),
    cta: ({ kind, offender }, context) =>
        offender ? openWorkflow(offender.workflow) : kind === 'complaint' ? manageOptOuts(context) : VIEW_WORKFLOWS,
})
