import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { InboxReportFeedbackSentiment } from '../../inboxAnalytics'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { useReportFeedbackCelebration } from './ReportFeedbackCelebration'

// Matches the cap on the sibling inbox dialogs (Dismiss, Refund, agent question); the note rides along as
// an analytics property, so keep it under the client's per-property limit.
const FEEDBACK_NOTE_MAX_LENGTH = 4000

/**
 * Thumbs rating at the end of the report body, where someone has just finished reading. The rating
 * submits on the first click, so there's no text field to mistake for the dismissal reason. Only
 * once it's recorded does a follow-up question appear, matched to the rating, so the note can
 * never gate the rating and ignoring it leaves the flow exactly as it was.
 */
export function ReportFeedbackFooter({
    report,
    align = 'start',
}: {
    report: SignalReport
    /** `end` pins the row to the right edge, for the summary column. */
    align?: 'start' | 'end'
}): JSX.Element {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const {
        feedbackSentiment,
        feedbackNoteDraft,
        feedbackNoteSent,
        feedbackSentNote,
        feedbackNoteSubmitting,
        feedbackDisabledReason,
    } = useValues(logic)
    const { rateReport, setFeedbackNoteDraft, submitFeedbackNote } = useActions(logic)

    const { celebrate, celebration } = useReportFeedbackCelebration()
    // Focus the question only in the instance that was clicked: the row is rendered on more than one
    // tab, and `LemonTabs` remounts tab content, so an unconditional `autoFocus` would grab focus on
    // every tab switch.
    const [askedHere, setAskedHere] = useState(false)
    const [questionDismissed, setQuestionDismissed] = useState(false)
    const sendNote = (): void => {
        if (feedbackNoteDraft.trim()) {
            submitFeedbackNote(feedbackNoteDraft)
        }
    }

    const isPositive = feedbackSentiment === 'positive'
    const isNegative = feedbackSentiment === 'negative'
    const rate = (sentiment: InboxReportFeedbackSentiment): void => {
        const nextSentiment = feedbackSentiment === sentiment ? null : sentiment
        rateReport(nextSentiment, 'detail_footer', nextSentiment === 'positive' ? celebrate : undefined)
        setQuestionDismissed(false)
        setAskedHere(true)
    }
    const askingWhy = !!feedbackSentiment && !feedbackNoteSent && !questionDismissed

    return (
        <div className={align === 'end' ? 'flex flex-col items-end gap-2 pt-1' : 'flex flex-col gap-2 pt-1'}>
            {/* `select-none` stays on the rating row: on the wrapper it would also cover the note
                textarea, where it blocks selecting text to edit or copy a draft. */}
            <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary select-none">
                {/* Both labels share one grid cell so the thumbs sit still when the text swaps. */}
                <span className={clsx('grid', align === 'end' && 'text-end')}>
                    <span
                        className={clsx('col-start-1 row-start-1', feedbackSentiment && 'invisible')}
                        aria-hidden={!!feedbackSentiment}
                    >
                        Was this report useful?
                    </span>
                    <span
                        className={clsx('col-start-1 row-start-1', !feedbackSentiment && 'invisible')}
                        aria-hidden={!feedbackSentiment}
                    >
                        Thanks for the feedback!
                    </span>
                </span>
                <div className="flex items-center gap-1">
                    <span className="relative inline-flex">
                        <LemonButton
                            size="xsmall"
                            type={isPositive ? 'primary' : 'secondary'}
                            icon={isPositive ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                            tooltip={isPositive ? 'Remove thumbs up' : 'Yes, this was useful'}
                            disabledReason={feedbackDisabledReason}
                            aria-label="This report was useful"
                            aria-pressed={isPositive}
                            onClick={() => rate('positive')}
                            data-attr="inbox-report-feedback-thumbs-up"
                        />
                        {celebration}
                    </span>
                    <LemonButton
                        size="xsmall"
                        type={isNegative ? 'primary' : 'secondary'}
                        icon={isNegative ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                        tooltip={isNegative ? 'Remove thumbs down' : "No, this wasn't useful"}
                        disabledReason={feedbackDisabledReason}
                        aria-label="This report was not useful"
                        aria-pressed={isNegative}
                        onClick={() => rate('negative')}
                        data-attr="inbox-report-feedback-thumbs-down"
                    />
                </div>
            </div>
            {/* The question lives under the row so it never pushes the thumbs sideways. */}
            {askingWhy && (
                <div
                    className="flex w-full max-w-96 flex-col gap-1.5 rounded border border-primary p-2"
                    data-attr="inbox-report-feedback-question"
                >
                    <div className="flex items-center gap-1">
                        <span className="grow text-xs font-medium text-primary">
                            {feedbackSentiment === 'positive' ? 'What made it useful?' : 'What was off?'}
                        </span>
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconX />}
                            aria-label="Dismiss"
                            onClick={() => setQuestionDismissed(true)}
                            data-attr="inbox-report-feedback-question-dismiss"
                        />
                    </div>
                    <div className="flex items-end gap-1.5">
                        {/* `className` lands on the inner textarea too, so the flex sizing stays on a wrapper. */}
                        <div className="min-w-0 flex-1">
                            <LemonTextArea
                                value={feedbackNoteDraft}
                                disabled={feedbackNoteSubmitting}
                                // Capped here rather than with `maxLength`, whose counter footer would
                                // make the small field a block.
                                onChange={(value) => setFeedbackNoteDraft(value.slice(0, FEEDBACK_NOTE_MAX_LENGTH))}
                                onPressEnter={sendNote}
                                placeholder="Your note improves future reports"
                                aria-label="Add a note about this report"
                                minRows={2}
                                maxRows={8}
                                autoFocus={askedHere}
                                className="resize-none"
                                data-attr="inbox-report-feedback-note"
                            />
                        </div>
                        {/* Shown only once there is text, so there is never a disabled button to look at. */}
                        {feedbackNoteDraft.trim() && (
                            <LemonButton
                                size="medium"
                                type="primary"
                                loading={feedbackNoteSubmitting}
                                onClick={sendNote}
                                data-attr="inbox-report-feedback-note-send"
                            >
                                Send
                            </LemonButton>
                        )}
                    </div>
                </div>
            )}
            {feedbackNoteSent && (
                <p className={clsx('m-0 max-w-96 text-xs text-tertiary', align === 'end' && 'text-end')}>
                    Note added: {feedbackSentNote}
                </p>
            )}
        </div>
    )
}
