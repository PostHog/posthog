import type { InsightLogicProps } from '~/types'

import { SentenceFollowUpWord } from '../followUps/SentenceFollowUpWord'
import type { SentencePart } from './buildSentence'
import { SentenceCompare } from './SentenceCompare'
import { SentenceDateRange } from './SentenceDateRange'
import { SentenceEvent } from './SentenceEvent'
import { SentenceFilters } from './SentenceFilters'
import { SentenceFormula } from './SentenceFormula'
import { SentenceFunnelActor } from './SentenceFunnelActor'
import { SentenceFunnelWindow } from './SentenceFunnelWindow'
import { SentenceInterval } from './SentenceInterval'
import { SentenceMeasure } from './SentenceMeasure'
import { SentenceMoreSeries } from './SentenceMoreSeries'
import { SentenceSeriesFilters } from './SentenceSeriesFilters'
import { SentenceSplit } from './SentenceSplit'

export function SentenceValue({
    insightProps,
    part,
}: {
    insightProps: InsightLogicProps
    part: Extract<SentencePart, { type: 'value' }>
}): JSX.Element {
    switch (part.slot) {
        case 'measure':
            return <SentenceMeasure insightProps={insightProps} seriesIndex={part.seriesIndex ?? 0} label={part.text} />
        case 'event':
            return <SentenceEvent insightProps={insightProps} seriesIndex={part.seriesIndex ?? 0} label={part.text} />
        case 'seriesFilters':
            return (
                <SentenceSeriesFilters
                    insightProps={insightProps}
                    seriesIndex={part.seriesIndex ?? 0}
                    label={part.text}
                />
            )
        case 'funnelActor':
            return <SentenceFunnelActor insightProps={insightProps} label={part.text} />
        case 'funnelWindow':
            return <SentenceFunnelWindow insightProps={insightProps} label={part.text} />
        case 'moreSeries':
            return <SentenceMoreSeries insightProps={insightProps} label={part.text} />
        case 'dateRange':
            return <SentenceDateRange insightProps={insightProps} label={part.text} />
        case 'interval':
            return <SentenceInterval insightProps={insightProps} label={part.text} />
        case 'compare':
            return <SentenceCompare insightProps={insightProps} label={part.text} />
        case 'split':
            return <SentenceSplit insightProps={insightProps} splitIndex={part.splitIndex ?? 0} label={part.text} />
        case 'filters':
            return <SentenceFilters insightProps={insightProps} label={part.text} />
        case 'formula':
            return <SentenceFormula insightProps={insightProps} label={part.text} />
        case 'subscription':
        case 'alert':
            return (
                <SentenceFollowUpWord
                    insightProps={insightProps}
                    slot={part.slot}
                    itemId={part.itemId ?? null}
                    label={part.text}
                />
            )
    }
}
