import { Fragment } from 'react'

import type { InsightLogicProps } from '~/types'

import { sentenceClauses } from './buildSentence'
import type { SentencePart } from './buildSentence'
import { SentenceValue } from './SentenceValue'

export function SentenceParts({
    insightProps,
    parts,
}: {
    insightProps: InsightLogicProps
    parts: SentencePart[]
}): JSX.Element {
    return (
        <>
            {sentenceClauses(parts).map((clause, clauseIndex) => (
                <Fragment key={clauseIndex}>
                    {clauseIndex > 0 && ' '}
                    {/* A clause moves to the next line whole, and wraps inside only when it is longer than a line. */}
                    <span className="inline-block max-w-full">
                        {clause.map((part, index) =>
                            part.type === 'text' ? (
                                <span key={index}>{part.text}</span>
                            ) : (
                                <SentenceValue key={index} insightProps={insightProps} part={part} />
                            )
                        )}
                    </span>
                </Fragment>
            ))}
        </>
    )
}
