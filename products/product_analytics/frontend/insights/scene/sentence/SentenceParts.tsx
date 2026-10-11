import { Fragment } from 'react'

import { cn } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { sentenceClauses } from './buildSentence'
import type { SentencePart } from './buildSentence'
import { SentenceValue } from './SentenceValue'

function isFormulaWord(part: SentencePart | undefined): boolean {
    return part?.type === 'value' && part.slot === 'formula'
}

export function SentenceParts({
    insightProps,
    parts,
}: {
    insightProps: InsightLogicProps
    parts: SentencePart[]
}): JSX.Element {
    const clauses = sentenceClauses(parts)
    return (
        <>
            {clauses.map((clause, clauseIndex) => (
                <Fragment key={clauseIndex}>
                    {clauseIndex > 0 && ' '}
                    {/* A clause moves to the next line whole, and wraps inside only when it is longer than a line.
                        A highlight bleeds past its word, so a formula word gets more room than one space on each side. */}
                    <span
                        className={cn(
                            'inline-block max-w-full',
                            isFormulaWord(clauses[clauseIndex + 1]?.[0]) && 'me-1.5'
                        )}
                    >
                        {clause.map((part, index) =>
                            part.type === 'text' ? (
                                <span
                                    key={index}
                                    className={
                                        part.text === ' ' && isFormulaWord(clause[index - 1]) ? 'ms-1.5' : undefined
                                    }
                                >
                                    {part.text}
                                </span>
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
