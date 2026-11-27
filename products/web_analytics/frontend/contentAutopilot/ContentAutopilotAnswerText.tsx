import clsx from 'clsx'
import { Fragment } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { percentage } from 'lib/utils/numbers'

import type { AEOBrandSentimentSentenceApi } from '../generated/api.schemas'
import type { AnswerMentions, AnswerSegment } from './answerMentions'
import { SENTIMENT_LABELS, answerSentimentBlocks } from './answerSentiment'

const SENTENCE_TINTS: Record<string, string> = {
    positive: 'bg-success',
    neutral: 'bg-fill-selected',
    negative: 'bg-destructive',
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
                    // Solid fills in the hues of the "You" and "Competitor" tags beside the answer. The status
                    // surfaces are the same pale tints as the sentence tints, so a brand inside a scored sentence
                    // would vanish on them. A span, not <mark>, because the base styles force a pale background on
                    // every <mark>.
                    ownKeys.has(segment.brandKey)
                        ? 'bg-success-foreground text-background'
                        : 'bg-warning-foreground text-background'
                )}
            >
                {segment.text}
            </span>
        ) : (
            <span key={key}>{segment.text}</span>
        )
    return (
        <div
            className="max-h-96 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-xs text-foreground"
            data-attr="content-autopilot-prompt-answer-text"
        >
            {!text
                ? 'The engine returned an empty answer.'
                : answerSentimentBlocks(text, mentions?.segments ?? [{ text, brandKey: null }], sentences).map(
                      (block, index) =>
                          block.sentence ? (
                              <Tooltip key={index}>
                                  <TooltipTrigger
                                      render={
                                          <span
                                              className={clsx(
                                                  'rounded-sm box-decoration-clone py-0.5',
                                                  SENTENCE_TINTS[block.sentence.label] ?? SENTENCE_TINTS.neutral
                                              )}
                                              data-attr="content-autopilot-prompt-answer-sentence"
                                          />
                                      }
                                  >
                                      {block.segments.map(renderSegment)}
                                  </TooltipTrigger>
                                  <TooltipContent>
                                      {`${SENTIMENT_LABELS[block.sentence.label] ?? block.sentence.label} about you (${percentage(block.sentence.score, 0)} confidence)`}
                                  </TooltipContent>
                              </Tooltip>
                          ) : (
                              <Fragment key={index}>{block.segments.map(renderSegment)}</Fragment>
                          )
                  )}
        </div>
    )
}
