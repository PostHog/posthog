import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconArrowRight, IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'

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
 * once it's recorded does an optional one-line note field appear under the row, so the note can
 * never gate the rating, and ignoring it leaves the flow exactly as it was.
 */
export function ReportFeedbackFooter({
    report,
    align = 'start',
}: {
    report: SignalReport
    /** `end` pins the row to the right edge, for the redesign's summary column. */
    align?: 'start' | 'end'
}): JSX.Element {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { feedbackSentiment, feedbackNoteDraft, feedbackNoteSent, feedbackSentNote, feedbackNoteSubmitting } =
        useValues(logic)
    const { rateReport, setFeedbackNoteDraft, submitFeedbackNote } = useActions(logic)

    const { celebrate, celebration } = useReportFeedbackCelebration()
    const sendNote = (): void => {
        if (feedbackNoteDraft.trim()) {
            submitFeedbackNote(feedbackNoteDraft)
        }
    }

    const isPositive = feedbackSentiment === 'positive'
    const isNegative = feedbackSentiment === 'negative'
    // Re-clicking the chosen thumb is a no-op rather than a second identical feedback event.
    const rate = (sentiment: InboxReportFeedbackSentiment): void => {
        if (feedbackSentiment === sentiment) {
            return
        }
        rateReport(sentiment)
        if (sentiment === 'positive') {
            celebrate()
        }
    }

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
                            tooltip="Yes, this was useful"
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
                        tooltip="No, this wasn't useful"
                        aria-label="This report was not useful"
                        aria-pressed={isNegative}
                        onClick={() => rate('negative')}
                        data-attr="inbox-report-feedback-thumbs-down"
                    />
                </div>
            </div>
            {/* The note lives under the row so it never pushes the thumbs sideways. */}
            {feedbackSentiment && !feedbackNoteSent && (
                <LemonInput
                    size="xsmall"
                    value={feedbackNoteDraft}
                    onChange={setFeedbackNoteDraft}
                    onPressEnter={sendNote}
                    placeholder="What was useful or off?"
                    // The placeholder is the only visible prompt and it disappears on the first
                    // keystroke, so the field carries its own name for screen readers.
                    aria-label="Add a note about this report"
                    maxLength={FEEDBACK_NOTE_MAX_LENGTH}
                    className="w-full max-w-64"
                    suffix={
                        <LemonButton
                            size="xsmall"
                            type="primary"
                            icon={<IconArrowRight />}
                            tooltip="Send note"
                            aria-label="Send note"
                            loading={feedbackNoteSubmitting}
                            disabledReason={feedbackNoteDraft.trim() ? undefined : 'Write a note first'}
                            onClick={sendNote}
                            data-attr="inbox-report-feedback-note-send"
                        />
                    }
                    data-attr="inbox-report-feedback-note"
                />
            )}
            {feedbackNoteSent && (
                <p className={clsx('m-0 max-w-64 text-xs text-tertiary', align === 'end' && 'text-end')}>
                    Note added: {feedbackSentNote}
                </p>
            )}
        </div>
    )
}
