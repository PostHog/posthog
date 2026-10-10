import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { insightSentenceLogic } from './insightSentenceLogic'
import { SentenceAddEvent } from './SentenceAddEvent'
import { SentenceAdditions } from './SentenceAdditions'
import { SentenceParts } from './SentenceParts'

export function InsightSentence({
    insightProps,
    trailing,
}: {
    insightProps: InsightLogicProps
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
        <div data-quill className="flex flex-col gap-3">
            <div className="flex flex-col text-xl leading-9 text-muted-foreground" data-attr="quill-insight-sentence">
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
                    <SentenceParts insightProps={insightProps} parts={sentence.parts} />
                </p>
            </div>
            <div className="flex items-start justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
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
