import clsx from 'clsx'
import { Fragment } from 'react'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { percentage } from 'lib/utils/numbers'

import type { AEOBrandSentimentSentenceApi } from '../generated/api.schemas'
import type { AnswerMentions, AnswerSegment } from './answerMentions'
import { SENTIMENT_LABELS, answerSentimentBlocks } from './answerSentiment'

// Mixed from the label's own token, because the ready-made highlight fills are too faint to read in dark mode.
const SENTENCE_TINTS: Record<string, string> = {
    positive: 'bg-[color-mix(in_oklab,var(--success)_22%,transparent)]',
    neutral: 'bg-[color-mix(in_oklab,var(--color-text-tertiary)_22%,transparent)]',
    negative: 'bg-[color-mix(in_oklab,var(--danger)_22%,transparent)]',
}

/** The engine's answer with our brand and confirmed competitors marked, so who the answer recommends reads at a
 *  glance. A sentence scored for sentiment is tinted in the color of its own label. */
export const ContentAutopilotAnswerText = ({
    text,
    mentions,
    sentences,
}: {
    text: string
    mentions: AnswerMentions | null
    sentences: AEOBrandSentimentSentenceApi[]
}): JSX.Element => {
    const ownKeys = new Set(mentions?.mentions.filter((m) => m.brand.isOwn).map((m) => m.brand.key))
    const renderSegment = (segment: AnswerSegment, key: number): JSX.Element =>
        segment.brandKey ? (
            <span
                key={key}
                className={clsx(
                    'rounded-sm px-1 font-semibold',
                    // Solid fills in the colors of the "You" and "Competitor" tags beside the answer. A span, not
                    // <mark>, because the base styles force a pale background on every <mark>.
                    ownKeys.has(segment.brandKey) ? 'bg-[var(--success)] text-white' : 'bg-[var(--warning)] text-black'
                )}
            >
                {segment.text}
            </span>
        ) : (
            <span key={key}>{segment.text}</span>
        )
    return (
        <div
            className="whitespace-pre-wrap break-words text-sm bg-surface-secondary rounded p-3 max-h-96 overflow-y-auto"
            data-attr="content-autopilot-prompt-answer-text"
        >
            {!text
                ? 'The engine returned an empty answer.'
                : answerSentimentBlocks(text, mentions?.segments ?? [{ text, brandKey: null }], sentences).map(
                      (block, index) =>
                          block.sentence ? (
                              <Tooltip
                                  key={index}
                                  title={`${SENTIMENT_LABELS[block.sentence.label] ?? block.sentence.label} about you (${percentage(block.sentence.score, 0)} confidence)`}
                              >
                                  <span
                                      className={clsx(
                                          'rounded-sm box-decoration-clone py-0.5',
                                          SENTENCE_TINTS[block.sentence.label] ?? SENTENCE_TINTS.neutral
                                      )}
                                      data-attr="content-autopilot-prompt-answer-sentence"
                                  >
                                      {block.segments.map(renderSegment)}
                                  </span>
                              </Tooltip>
                          ) : (
                              <Fragment key={index}>{block.segments.map(renderSegment)}</Fragment>
                          )
                  )}
        </div>
    )
}
