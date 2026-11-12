import clsx from 'clsx'

import type { AnswerMentions } from './answerMentions'

/** The engine's answer with our brand and confirmed competitors marked, so who the answer recommends reads at a
 *  glance. */
export const ContentAutopilotAnswerText = ({
    text,
    mentions,
}: {
    text: string
    mentions: AnswerMentions | null
}): JSX.Element => {
    const ownKeys = new Set(mentions?.mentions.filter((m) => m.brand.isOwn).map((m) => m.brand.key))
    return (
        <div
            className="whitespace-pre-wrap break-words text-sm bg-surface-secondary rounded p-3 max-h-96 overflow-y-auto"
            data-attr="content-autopilot-prompt-answer-text"
        >
            {!text
                ? 'The engine returned an empty answer.'
                : !mentions
                  ? text
                  : mentions.segments.map((segment, index) =>
                        segment.brandKey ? (
                            <span
                                key={index}
                                className={clsx(
                                    'rounded-sm px-1 font-semibold',
                                    // Solid fills in the colors of the "You" and "Competitor" tags beside the answer. A span, not
                                    // <mark>, because the base styles force a pale background on every <mark>.
                                    ownKeys.has(segment.brandKey)
                                        ? 'bg-[var(--success)] text-white'
                                        : 'bg-[var(--warning)] text-black'
                                )}
                            >
                                {segment.text}
                            </span>
                        ) : (
                            <span key={index}>{segment.text}</span>
                        )
                    )}
        </div>
    )
}
