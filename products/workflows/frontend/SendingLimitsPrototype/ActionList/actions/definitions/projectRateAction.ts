import {
    ExceededLevel,
    RATE_KINDS,
    RATE_KIND_LIST,
    RATE_THRESHOLDS,
    RateKind,
    exceededLevel,
    formatRate,
    rateOf,
} from '../../reputationUtils'
import { defineReputationAction } from '../defineReputationAction'
import { LOWER_RATES_DOCS, VIEW_WORKFLOWS, manageOptOuts } from '../reputationActionCtas'

interface ProjectRate {
    kind: RateKind
    rate: number
    level: ExceededLevel
}

/**
 * The whole project is over a line, but no finding or workflow row already says so. Many small
 * workflows can each sit under the volume floor while together they put the project over a line.
 */
export const projectRateAction = defineReputationAction<ProjectRate>({
    kind: 'project-rate',
    detect: ({ response, hasRateFinding, workflowsOverLine }) =>
        RATE_KIND_LIST.flatMap((kind) => {
            const rates = response.reputation
            if (!rates || hasRateFinding(kind) || workflowsOverLine(kind).length > 0) {
                return []
            }
            const rate = rateOf(rates, kind)
            const level = exceededLevel(rate, kind, rates.emails_sent)
            return level ? [{ kind, rate, level }] : []
        }),
    content: ({ kind, rate, level }) => ({
        key: `project-${kind}`,
        rank: {
            severity: level === 'high' ? 'high' : 'medium',
            slot: 'projectRate',
            rateKind: kind,
            magnitude: rate / RATE_THRESHOLDS[kind].elevated,
        },
        title: `Your project has a ${formatRate(rate)} ${RATE_KINDS[kind].event} rate`,
        description:
            kind === 'bounce'
                ? 'No single workflow stands out, so the bounces come from many smaller sends. Check where your audiences come from, and stop sending to imported or purchased lists.'
                : 'No single workflow stands out, so the complaints come from many smaller sends. Send only to people who opted in, and make unsubscribing easy.',
        docsLink: LOWER_RATES_DOCS,
    }),
    cta: ({ kind }, context) => (kind === 'complaint' ? manageOptOuts(context) : VIEW_WORKFLOWS),
})
