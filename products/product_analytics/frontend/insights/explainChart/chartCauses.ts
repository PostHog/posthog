import type { ChartCauseEnumApi } from 'products/product_analytics/frontend/generated/api.schemas'
import type { StoryConfidence } from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'
import { mark } from 'products/product_analytics/mcp/apps/explainChart/storyMarks'

import type { ChartMoment } from './chartMoments'
import type { MomentEvidence } from './momentEvidence'

export interface ModelCause {
    cause: ChartCauseEnumApi
    confidence: number
}

export interface ChapterCause {
    /** Lower case, so the headline can follow a step's title with it. */
    clause: string
    confidence: StoryConfidence
}

export interface ExplainedMoment {
    moment: ChartMoment
    cause: ChapterCause | null
}

const MIN_MODEL_CONFIDENCE = 0.5
const HIGH_MODEL_CONFIDENCE = 0.8
const HIGH_CONFIDENCE_SHARE = 0.8

function strongestDriver(evidence: MomentEvidence[], key?: string): string | null {
    const named = evidence
        .filter((item) => item.driver && (!key || item.driver.key === key))
        .sort((a, b) => (b.driverShare ?? 0) - (a.driverShare ?? 0))
    return named[0]?.driver?.value ?? null
}

function shareConfidence(evidence: MomentEvidence[]): StoryConfidence {
    const shares = evidence.map((item) => item.driverShare).filter((share): share is number => share !== null)
    if (!shares.length) {
        return 'low'
    }
    return Math.max(...shares) >= HIGH_CONFIDENCE_SHARE ? 'high' : 'medium'
}

function clauseFor(cause: ChartCauseEnumApi, moment: ChartMoment, evidence: MomentEvidence[]): string {
    switch (cause) {
        case 'outside_traffic': {
            const referrer = strongestDriver(evidence, '$referring_domain')
            const amount = moment.direction === 'up' ? 'more' : 'fewer'
            return referrer
                ? `most likely ${amount} people arriving from ${mark('name', referrer)}`
                : `most likely ${amount} people arriving from outside, such as from a launch, a post or a campaign`
        }
        case 'usage': {
            const page = strongestDriver(evidence, '$pathname')
            return `most likely a real change in how people use ${page ? mark('name', page) : 'the product'}`
        }
        case 'one_person':
            return 'most likely one person, a bot or a test account, not a change in how people use the product'
        case 'tracking':
            return 'most likely a tracking change, such as events that stopped or were sent twice, not a change in how people use the product'
        case 'weekly_pattern':
            return 'most likely the usual weekly pattern, not a real change'
    }
}

/** The likely cause of a step. What the evidence shows outranks the model, and the model outranks a bare driver. */
export function chapterCause(
    moment: ChartMoment,
    evidence: MomentEvidence[],
    model: ModelCause | null
): ChapterCause | null {
    if (evidence.some((item) => item.cause === 'one_person')) {
        return { clause: clauseFor('one_person', moment, evidence), confidence: 'high' }
    }
    if (model && model.confidence >= MIN_MODEL_CONFIDENCE) {
        // Without evidence, the model only reads the step's own numbers, so its answer stays a guess.
        const confidence = !evidence.length ? 'low' : model.confidence >= HIGH_MODEL_CONFIDENCE ? 'high' : 'medium'
        return { clause: clauseFor(model.cause, moment, evidence), confidence }
    }
    if (evidence.some((item) => item.cause === 'tracking')) {
        return { clause: clauseFor('tracking', moment, evidence), confidence: 'low' }
    }
    const driver = strongestDriver(evidence)
    return driver
        ? { clause: `most likely linked to ${mark('name', driver)}`, confidence: shareConfidence(evidence) }
        : null
}

export function causeSentence(cause: ChapterCause): string {
    return `${cause.clause.charAt(0).toUpperCase()}${cause.clause.slice(1)}.`
}

export function headlineText(explained: ExplainedMoment[]): string {
    if (!explained.length) {
        return 'Nothing unusual stands out on this chart.'
    }
    const [lead, ...rest] = explained
    const main = lead.cause ? `${lead.moment.title}, ${lead.cause.clause}.` : `${lead.moment.title}.`
    if (!rest.length) {
        return main
    }
    return `${main} ${rest.length} more ${rest.length === 1 ? 'thing stands' : 'things stand'} out.`
}
