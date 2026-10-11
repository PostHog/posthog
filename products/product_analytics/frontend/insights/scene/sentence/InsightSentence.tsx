import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { insightSentenceLogic } from './insightSentenceLogic'
import { SentenceAddEvent } from './SentenceAddEvent'
import { SentenceAdditions } from './SentenceAdditions'
import { SentenceParts } from './SentenceParts'

export function InsightSentence({
    insightProps,
    ending,
    trailing,
}: {
    insightProps: InsightLogicProps
    ending?: React.ReactNode
    /** Shown at the end of the row of additions. */
    trailing?: React.ReactNode
}): JSX.Element | null {
    const { sentence } = useValues(insightSentenceLogic(insightProps))
    const { setSeriesExpanded } = useActions(insightSentenceLogic(insightProps))

    if (!sentence) {
        return null
    }

    const showsSeriesLines = sentence.seriesLines.length > 0

    return (
        <div data-quill className="group/sentence flex flex-col gap-3">
            <div className="flex flex-col text-xl leading-9 text-muted-foreground" data-attr="quill-insight-sentence">
                {sentence.lead.length > 0 && (
                    <p className="m-0 text-pretty">
                        <SentenceParts insightProps={insightProps} parts={sentence.lead} />
                    </p>
                )}
                {showsSeriesLines && (
                    <ul className="m-0 flex list-none flex-col p-0">
                        {sentence.seriesLines.map((line, index) => (
                            <li key={index}>
                                <SentenceParts insightProps={insightProps} parts={line} />
                            </li>
                        ))}
                    </ul>
                )}
                <p className="m-0 text-pretty">
                    <SentenceParts insightProps={insightProps} parts={sentence.parts} ending={ending} />
                </p>
            </div>
            <div className="flex items-start justify-between gap-2">
                {/* Only the faint state has the delay and the slow fade, so the buttons light up quickly. */}
                <div className="flex flex-wrap items-center gap-2 opacity-50 transition-opacity delay-1000 duration-700 group-focus-within/sentence:opacity-100 group-focus-within/sentence:delay-0 group-focus-within/sentence:duration-150 group-hover/sentence:opacity-100 group-hover/sentence:delay-0 group-hover/sentence:duration-150 has-[[aria-expanded=true]]:opacity-100 has-[[aria-expanded=true]]:delay-0 has-[[aria-expanded=true]]:duration-150">
                    <SentenceAdditions insightProps={insightProps} />
                    <SentenceAddEvent insightProps={insightProps} />
                    {sentence.canCollapseSeries && (
                        <Button
                            variant="link-muted"
                            size="sm"
                            onClick={() => setSeriesExpanded(false)}
                            data-attr="quill-insight-sentence-collapse-series"
                        >
                            Show fewer events
                        </Button>
                    )}
                </div>
                {trailing}
            </div>
        </div>
    )
}
