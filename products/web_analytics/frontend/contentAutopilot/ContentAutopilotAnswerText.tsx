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
                            <mark
                                key={index}
                                className={clsx(
                                    'rounded-sm px-0.5 text-primary border-b-2',
                                    ownKeys.has(segment.brandKey)
                                        ? 'bg-success-highlight border-success'
                                        : 'bg-warning-highlight border-warning'
                                )}
                            >
                                {segment.text}
                            </mark>
                        ) : (
                            <span key={index}>{segment.text}</span>
                        )
                    )}
        </div>
    )
}
