import { capitalizeFirstLetter } from 'lib/utils/strings'

import { partsAfterSeries, seriesEventParts, withoutLeadingComma } from './buildSentence'
import type {
    FunnelSentenceDetails,
    FunnelView,
    Sentence,
    SentenceInput,
    SentenceOptions,
    SentencePart,
} from './buildSentence'

const STEP_LINES_FROM = 4

const STEPS_INLINE_MAX_LENGTH = 80

// What each view measures decides how the sentence opens. The actor word sits between `prefix` and the verb.
const PHRASES: Record<FunnelView, { prefix: string; from: string; did: string }> = {
    steps: { prefix: '', from: ' who went from ', did: ' who did ' },
    trends: { prefix: 'Share of ', from: ' who went from ', did: ' who did ' },
    time_to_convert: { prefix: 'Time ', from: ' took to go from ', did: ' took to do ' },
}

function text(value: string): SentencePart {
    return { type: 'text', text: value }
}

function opening(funnel: FunnelSentenceDetails, verb: string): SentencePart[] {
    const { prefix } = PHRASES[funnel.view]
    const actor: SentencePart = {
        type: 'value',
        slot: 'funnelActor',
        text: prefix ? funnel.actor : capitalizeFirstLetter(funnel.actor),
    }
    return [...(prefix ? [text(prefix)] : []), actor, text(verb)]
}

function textLength(parts: SentencePart[]): number {
    return parts.reduce((length, part) => length + part.text.length, 0)
}

export function buildFunnelSentence(input: SentenceInput, options: SentenceOptions): Sentence {
    const funnel = input.funnel
    const afterSteps = partsAfterSeries(input, options)
    if (!funnel) {
        return { lead: [], seriesLines: [], parts: afterSteps, canCollapseSeries: false }
    }
    const phrases = PHRASES[funnel.view]
    const steps = input.series.map((series, seriesIndex) => seriesEventParts(series, seriesIndex, options))

    if (!steps.length) {
        return {
            lead: [],
            seriesLines: [],
            parts: [...opening(funnel, ' with no steps yet'), ...afterSteps],
            canCollapseSeries: false,
        }
    }

    const ordered = steps.length > 1 && !funnel.anyOrder
    const inline: SentencePart[] = [
        ...opening(funnel, ordered ? phrases.from : phrases.did),
        ...steps.flatMap((step, index) => [...(index > 0 ? [text(ordered ? ' to ' : ' and ')] : []), ...step]),
        ...(steps.length > 1 && funnel.anyOrder ? [text(' in any order')] : []),
    ]
    if (steps.length < STEP_LINES_FROM && textLength(inline) <= STEPS_INLINE_MAX_LENGTH) {
        return { lead: [], seriesLines: [], parts: [...inline, ...afterSteps], canCollapseSeries: false }
    }

    return {
        lead: opening(funnel, `${phrases.did}these steps ${funnel.anyOrder ? 'in any order' : 'in order'}:`),
        seriesLines: steps.map((step, index) => [
            text(`${index + 1}. `),
            ...step,
            ...(index === steps.length - 1 ? [text(',')] : []),
        ]),
        parts: withoutLeadingComma(afterSteps),
        canCollapseSeries: false,
    }
}
